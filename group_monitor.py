"""Acompanhamento de um grupo de periódicos em processamento.

Mede, para as revistas marcadas: o que já foi feito, o que falta, a velocidade
atual e a previsão de término do grupo. Usado pelo painel (/monitor) e pela
linha de comando:

    venv/bin/python group_monitor.py --ids 50,27,24,103,8,28
"""
import argparse
import datetime

from sqlalchemy import func

from database import (get_session, Journal, Edition, Article, File,
                      CapturedEmail, ExecutionRun)
from journal_sizer import latest_estimates

# Artigos que já renderam o que tinham para render
STATUS_DONE = ('completed', 'completed_foreign')
STATUS_NO_PDF = ('no_pdf',)
# Fila do crawler (baixar o PDF) e do processador (extrair e-mails do PDF)
STATUS_QUEUE_DOWNLOAD = ('found', 'processing_crawling')
STATUS_QUEUE_EXTRACT = ('downloaded', 'processing_extraction')
# Em andamento neste instante (algum worker segurando a tarefa)
STATUS_RUNNING = ('processing_crawling', 'processing_extraction')

DEFAULT_WINDOW_MINUTES = 10


def _utcnow():
    # naive em UTC, como os timestamps gravados pelo crawler
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _article_status_counts(session, journal_ids):
    """{journal_id: {status: n}} — uma varredura só para todo o grupo."""
    rows = session.query(Edition.journal_id, Article.status, func.count(Article.id))\
        .join(Article, Article.edition_id == Edition.id)\
        .filter(Edition.journal_id.in_(journal_ids))\
        .group_by(Edition.journal_id, Article.status).all()
    out = {jid: {} for jid in journal_ids}
    for jid, status, n in rows:
        out.setdefault(jid, {})[status or 'found'] = n
    return out


def _edition_status_counts(session, journal_ids):
    rows = session.query(Edition.journal_id, Edition.status, func.count(Edition.id))\
        .filter(Edition.journal_id.in_(journal_ids))\
        .group_by(Edition.journal_id, Edition.status).all()
    out = {jid: {} for jid in journal_ids}
    for jid, status, n in rows:
        out.setdefault(jid, {})[status or 'found'] = n
    return out


def _files_since(session, journal_ids, since):
    """PDFs gravados depois de `since`, por periódico."""
    if since is None:
        return {}
    rows = session.query(Edition.journal_id, func.count(File.id))\
        .join(Article, Article.edition_id == Edition.id)\
        .join(File, File.article_id == Article.id)\
        .filter(Edition.journal_id.in_(journal_ids), File.created_at >= since)\
        .group_by(Edition.journal_id).all()
    return {jid: n for jid, n in rows}


def _email_counts(session, journal_ids):
    """{journal_id: (total_encontrados, validos_distintos)}"""
    total_rows = session.query(Edition.journal_id, func.count(CapturedEmail.id))\
        .join(Article, Article.edition_id == Edition.id)\
        .join(CapturedEmail, CapturedEmail.article_id == Article.id)\
        .filter(Edition.journal_id.in_(journal_ids))\
        .group_by(Edition.journal_id).all()
    valid_rows = session.query(Edition.journal_id, func.count(func.distinct(CapturedEmail.email)))\
        .join(Article, Article.edition_id == Edition.id)\
        .join(CapturedEmail, CapturedEmail.article_id == Article.id)\
        .filter(Edition.journal_id.in_(journal_ids),
                CapturedEmail.verification_status == 'VALID')\
        .group_by(Edition.journal_id).all()
    totals = dict(total_rows)
    valids = dict(valid_rows)
    return {jid: (totals.get(jid, 0), valids.get(jid, 0)) for jid in journal_ids}


def _sum(counts, statuses):
    return sum(counts.get(s, 0) for s in statuses)


def _errors(counts):
    return sum(n for s, n in counts.items() if s and s.startswith('error'))


def snapshot(session, journal_ids, started_at=None, window_minutes=DEFAULT_WINDOW_MINUTES):
    """Fotografia do grupo: feito, fila, velocidade e previsão de término.

    `started_at` (UTC) é o marco do acompanhamento: dele saem o tempo decorrido
    e a velocidade média, que é o que sustenta a previsão de horas ou dias.
    """
    journal_ids = [int(j) for j in journal_ids]
    now = _utcnow()

    if not journal_ids:
        return {'generated_at': now, 'started_at': started_at, 'journals': [],
                'totals': _empty_totals(), 'window_minutes': window_minutes,
                'rate_now': 0.0, 'rate_avg': None, 'rate_used': 0.0,
                'eta_minutes': None, 'eta_at': None, 'eta_now_minutes': None,
                'elapsed_seconds': None, 'done_since_start': 0}

    journals = session.query(Journal).filter(Journal.id.in_(journal_ids)).all()
    by_id = {j.id: j for j in journals}
    art = _article_status_counts(session, journal_ids)
    edi = _edition_status_counts(session, journal_ids)
    emails = _email_counts(session, journal_ids)
    estimates = latest_estimates(session, journal_ids, only_ok=True)

    window_start = now - datetime.timedelta(minutes=window_minutes)
    recent = _files_since(session, journal_ids, window_start)
    since_start = _files_since(session, journal_ids, started_at) if started_at else {}

    rows = []
    for jid in journal_ids:
        j = by_id.get(jid)
        if j is None:
            continue
        counts = art.get(jid, {})
        ed_counts = edi.get(jid, {})

        in_db = sum(counts.values())
        done = _sum(counts, STATUS_DONE)
        no_pdf = _sum(counts, STATUS_NO_PDF)
        errors = _errors(counts)
        queue_download = _sum(counts, STATUS_QUEUE_DOWNLOAD)
        queue_extract = _sum(counts, STATUS_QUEUE_EXTRACT)
        editions_pending = ed_counts.get('found', 0) + ed_counts.get('processing', 0)

        # Artigos que as edições ainda fechadas devem revelar. Sem edição
        # pendente não há mais nada a descobrir, mesmo que o site tenha mais.
        est = estimates.get(jid)
        site_articles = est.articles_count if est and est.articles_count else None
        to_discover = 0
        if editions_pending and site_articles:
            to_discover = max(0, site_articles - in_db)

        target = in_db + to_discover
        pending = queue_download + queue_extract + to_discover
        resolved = done + no_pdf + errors
        pct = round(resolved / target * 100, 1) if target else 0.0

        total_emails, valid_emails = emails.get(jid, (0, 0))
        rows.append({
            'id': jid,
            'name': j.name,
            'source_type': j.source_type,
            'site_articles': site_articles,
            'site_exact': bool(est.is_exact) if est else False,
            'in_db': in_db,
            'target': target,
            'done': done,
            'no_pdf': no_pdf,
            'errors': errors,
            'queue_download': queue_download,
            'queue_extract': queue_extract,
            'editions_pending': editions_pending,
            'to_discover': to_discover,
            'pending': pending,
            'pct': pct,
            'emails': total_emails,
            'emails_valid': valid_emails,
            'recent_pdfs': recent.get(jid, 0),
            'running': _sum(counts, STATUS_RUNNING) > 0 or recent.get(jid, 0) > 0,
            'finished': pending == 0,
        })

    totals = {
        'journals': len(rows),
        'target': sum(r['target'] for r in rows),
        'in_db': sum(r['in_db'] for r in rows),
        'done': sum(r['done'] for r in rows),
        'no_pdf': sum(r['no_pdf'] for r in rows),
        'errors': sum(r['errors'] for r in rows),
        'queue_download': sum(r['queue_download'] for r in rows),
        'queue_extract': sum(r['queue_extract'] for r in rows),
        'to_discover': sum(r['to_discover'] for r in rows),
        'pending': sum(r['pending'] for r in rows),
        'emails': sum(r['emails'] for r in rows),
        'emails_valid': sum(r['emails_valid'] for r in rows),
        'finished_journals': sum(1 for r in rows if r['finished']),
        'running_journals': sum(1 for r in rows if r['running']),
    }
    totals['resolved'] = totals['done'] + totals['no_pdf'] + totals['errors']
    totals['pct'] = round(totals['resolved'] / totals['target'] * 100, 1) if totals['target'] else 0.0

    # Velocidade: a recente mostra o ritmo agora, a média sustenta a previsão.
    rate_now = round(sum(recent.values()) / float(window_minutes), 2)
    elapsed_seconds = None
    rate_avg = None
    done_since_start = sum(since_start.values())
    if started_at:
        elapsed_seconds = max(0, int((now - started_at).total_seconds()))
        elapsed_min = elapsed_seconds / 60.0
        if elapsed_min >= 2:
            rate_avg = round(done_since_start / elapsed_min, 2)

    # A média manda quando existe; o ritmo atual entra se a média ainda não
    # tem lastro (acompanhamento recém-iniciado).
    rate_used = rate_avg if rate_avg else rate_now
    eta_minutes = max(1, int(round(totals['pending'] / rate_used))) if rate_used and totals['pending'] else (0 if not totals['pending'] else None)
    eta_now_minutes = max(1, int(round(totals['pending'] / rate_now))) if rate_now and totals['pending'] else (0 if not totals['pending'] else None)
    eta_at = now + datetime.timedelta(minutes=eta_minutes) if eta_minutes else (now if eta_minutes == 0 else None)

    for r in rows:
        r['eta_minutes'] = max(1, int(round(r['pending'] / rate_used))) if rate_used and r['pending'] else (0 if not r['pending'] else None)

    return {
        'generated_at': now,
        'started_at': started_at,
        'elapsed_seconds': elapsed_seconds,
        'done_since_start': done_since_start,
        'window_minutes': window_minutes,
        'rate_now': rate_now,
        'rate_avg': rate_avg,
        'rate_used': rate_used,
        'eta_minutes': eta_minutes,
        'eta_now_minutes': eta_now_minutes,
        'eta_at': eta_at,
        'journals': rows,
        'totals': totals,
    }


def _empty_totals():
    return {'journals': 0, 'target': 0, 'in_db': 0, 'done': 0, 'no_pdf': 0, 'errors': 0,
            'queue_download': 0, 'queue_extract': 0, 'to_discover': 0, 'pending': 0,
            'emails': 0, 'emails_valid': 0, 'resolved': 0, 'pct': 0.0,
            'finished_journals': 0, 'running_journals': 0}


def format_duration(seconds):
    """3h 05m — o formato que o painel usa nos cartões."""
    if seconds is None:
        return '—'
    seconds = int(seconds)
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    if d:
        return f"{d}d {h:02d}h {m:02d}m"
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"


def format_minutes(minutes):
    if minutes is None:
        return 'indefinido'
    if minutes <= 0:
        return 'concluído'
    return format_duration(minutes * 60)


def main():
    parser = argparse.ArgumentParser(description="Acompanhamento de um grupo de periódicos")
    parser.add_argument('--ids', required=True, help="IDs separados por vírgula, ex: 50,27,24")
    parser.add_argument('--since', help="Início do acompanhamento (UTC, 'YYYY-MM-DD HH:MM'). Padrão: início do run mais antigo em andamento")
    parser.add_argument('--window', type=int, default=DEFAULT_WINDOW_MINUTES, help="Janela da velocidade atual, em minutos")
    args = parser.parse_args()

    ids = [int(x) for x in args.ids.replace(' ', '').split(',') if x]
    session = get_session()
    try:
        started_at = None
        if args.since:
            started_at = datetime.datetime.strptime(args.since, '%Y-%m-%d %H:%M')
        else:
            started_at = first_run_start(session, ids)

        snap = snapshot(session, ids, started_at=started_at, window_minutes=args.window)
        t = snap['totals']
        print(f"\nGrupo: {t['journals']} periódicos · {t['finished_journals']} concluídos · {t['running_journals']} em andamento")
        print(f"Progresso: {t['resolved']:,} de {t['target']:,} artigos ({t['pct']}%) · {t['emails']:,} e-mails ({t['emails_valid']:,} válidos)".replace(',', '.'))
        print(f"Decorrido: {format_duration(snap['elapsed_seconds'])} · velocidade {snap['rate_now']}/min agora, {snap['rate_avg'] or '—'}/min na média")
        print(f"Falta: {t['pending']:,} artigos · previsão {format_minutes(snap['eta_minutes'])}".replace(',', '.'), end='')
        if snap['eta_at']:
            local = snap['eta_at'] + (datetime.datetime.now() - _utcnow())
            print(f" (termina ~{local.strftime('%d/%m %H:%M')})")
        else:
            print()
        print()
        print(f"{'ID':>4}  {'Periódico':<32} {'feito':>7} {'fila':>7} {'alvo':>7} {'%':>6}  previsão")
        for r in snap['journals']:
            print(f"{r['id']:>4}  {r['name'][:32]:<32} {r['done']:>7} {r['pending']:>7} {r['target']:>7} {r['pct']:>5}%  {format_minutes(r['eta_minutes'])}")
        print()
    finally:
        session.close()


def first_run_start(session, journal_ids):
    """Início do run mais antigo ainda em execução para o grupo (fallback do CLI)."""
    row = session.query(func.min(ExecutionRun.start_time))\
        .filter(ExecutionRun.journal_id.in_(journal_ids),
                ExecutionRun.status == 'running').scalar()
    return row


if __name__ == '__main__':
    main()
