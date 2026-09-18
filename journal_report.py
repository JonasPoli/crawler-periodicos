"""
Relatório de cobertura dos periódicos: o que cada site tem (medido pelo journal_sizer), o que já
analisamos, o que ainda falta e o que não dá para extrair.

Regras das contagens do banco:
  - Só artigos do próprio periódico (URL sob a raiz da revista): versões antigas do crawler vazavam
    para outros sites e baixavam PDFs alheios.
  - Cada artigo conta uma vez (mesma URL em várias edições, ou /abstract/ do SciELO, é o mesmo).
  - "Analisado" = PDF processado (status completed) OU artigo que já tem e-mails capturados:
    reset_journal_for_rerun volta artigos processados para 'found' sem apagar os e-mails.

Estimativas usam a média de e-mails por PDF do sistema (system_emails_per_pdf).
"""
import csv
import datetime
import io
import json
import time

from sqlalchemy import text

from database import Journal
from journal_sizer import (ARTICLE_PREFIX_SQL, estimated_emails, is_own_prefix, journal_own_keys,
                           latest_estimates, system_emails_per_pdf)

ANALYZED, NO_PDF, ERROR, QUEUED = 4, 3, 2, 1

# Um artigo conta uma vez, no melhor estado entre as cópias. Mesmo artigo = mesma raiz + mesmo id
# (1º segmento após /article/view/ ou /a/): ignora galé, /abstract/, ?lang=... e http/https/www,
# variações que versões antigas do crawler gravavam como artigos diferentes.
ARTICLE_STATES_SQL = text(f"""
    WITH base AS (
        SELECT e.journal_id AS journal_id,
               {ARTICLE_PREFIX_SQL} AS prefix,
               CASE WHEN instr(a.url, '/article/view/') > 0 THEN substr(a.url, instr(a.url, '/article/view/') + 14)
                    WHEN instr(a.url, '/a/') > 0 THEN substr(a.url, instr(a.url, '/a/') + 3)
                    ELSE a.url END AS rest,
               CASE WHEN a.status = 'completed' OR c.n > 0 THEN {ANALYZED}
                    WHEN a.status = 'no_pdf' THEN {NO_PDF}
                    WHEN a.status LIKE 'error%' THEN {ERROR}
                    ELSE {QUEUED} END AS state,
               COALESCE(c.n, 0) AS emails
        FROM articles a
        JOIN editions e ON e.id = a.edition_id
        LEFT JOIN (SELECT article_id, COUNT(*) AS n FROM captured_emails GROUP BY article_id) c
               ON c.article_id = a.id
    ),
    art AS (
        SELECT journal_id, prefix, MAX(state) AS state, MAX(emails) AS emails
        FROM base
        GROUP BY journal_id,
                 replace(replace(replace(replace(lower(prefix), 'https://', ''), 'http://', ''), 'www.', ''), '/index.php', ''),
                 CASE WHEN instr(rest, '/') > 0 THEN substr(rest, 1, instr(rest, '/') - 1)
                      WHEN instr(rest, '?') > 0 THEN substr(rest, 1, instr(rest, '?') - 1)
                      ELSE rest END
    )
    SELECT journal_id, prefix, state, COUNT(*) AS articles, SUM(emails) AS emails
    FROM art
    GROUP BY 1, 2, 3
""")

# E-mails distintos (por periódico e no total), só de artigos cujas raízes estão em "own"
UNIQUE_EMAILS_SQL = """
    WITH own(journal_id, prefix) AS (VALUES {values}),
    em AS (
        SELECT e.journal_id AS journal_id, lower(trim(ce.email)) AS email, ce.verification_status AS status
        FROM captured_emails ce
        JOIN articles a ON a.id = ce.article_id
        JOIN editions e ON e.id = a.edition_id
        JOIN own ON own.journal_id = e.journal_id AND own.prefix = {prefix}
    )
    SELECT journal_id, COUNT(DISTINCT email), COUNT(DISTINCT CASE WHEN status = 'VALID' THEN email END)
    FROM em GROUP BY journal_id
    UNION ALL
    SELECT NULL, COUNT(DISTINCT email), COUNT(DISTINCT CASE WHEN status = 'VALID' THEN email END)
    FROM em
"""

EMPTY_COVERAGE = {'articles': 0, 'analyzed': 0, 'no_pdf': 0, 'errors': 0, 'queued': 0,
                  'emails_found': 0, 'emails_unique': 0, 'emails_valid': 0}

SITUATION_LABELS = {
    'extraivel': 'Extraível',
    'bloqueado': 'Bloqueado por anti-bot: extração impossível',
    'falha_medicao': 'Falha na medição do site',
    'nao_medido': 'Não medido',
}

_coverage_cache = {'at': 0.0, 'value': None}


def db_coverage(session, max_age=300):
    """
    O que o banco tem de cada periódico (só artigos próprios, deduplicados). As consultas levam alguns
    segundos, então o resultado fica em cache por max_age segundos.
    """
    if _coverage_cache['value'] and time.time() - _coverage_cache['at'] < max_age:
        return _coverage_cache['value']

    own_keys = journal_own_keys(session)
    journals, own_pairs = {}, set()
    for journal_id, prefix, state, articles, emails in session.execute(ARTICLE_STATES_SQL).fetchall():
        if not is_own_prefix(prefix, own_keys.get(journal_id, ())):
            continue
        own_pairs.add((journal_id, prefix))
        cov = journals.setdefault(journal_id, dict(EMPTY_COVERAGE))
        field = {ANALYZED: 'analyzed', NO_PDF: 'no_pdf', ERROR: 'errors', QUEUED: 'queued'}[state]
        cov[field] += articles
        cov['articles'] += articles
        cov['emails_found'] += emails or 0

    unique_total = valid_total = 0
    if own_pairs:
        pairs = sorted(own_pairs)
        params = {}
        for i, (journal_id, prefix) in enumerate(pairs):
            params[f'j{i}'], params[f'p{i}'] = journal_id, prefix
        values = ', '.join(f'(:j{i}, :p{i})' for i in range(len(pairs)))
        sql = text(UNIQUE_EMAILS_SQL.format(values=values, prefix=ARTICLE_PREFIX_SQL))
        for journal_id, unique, valid in session.execute(sql, params).fetchall():
            if journal_id is None:
                unique_total, valid_total = unique, valid
            else:
                journals[journal_id].update(emails_unique=unique, emails_valid=valid)

    value = {'journals': journals, 'unique_total': unique_total, 'valid_total': valid_total,
             'computed_at': datetime.datetime.utcnow()}
    _coverage_cache.update(at=time.time(), value=value)
    return value


def report_row(journal, est, cov, avg):
    """Junta medição do site + cobertura do banco + estimativas de um periódico."""
    measured = est is not None and est.status == 'ok' and est.articles_count is not None
    blocked = est.blocked_by if est is not None else None
    site = est.articles_count if measured else None
    done = cov['analyzed'] + cov['no_pdf']  # desses não há mais o que extrair
    details = json.loads(est.details) if est is not None and est.details else {}
    warnings = list(details.get('warnings') or [])

    site_exact = bool(measured and est.is_exact)
    if site is not None and cov['articles'] > site:
        if site_exact:
            # Contagem exata do site: o excesso no banco são URLs alternativas ou artigos que saíram do site
            warnings.append(f"Banco tem {cov['articles']} artigos próprios, mais que os {site} do site "
                            f"(URLs alternativas ou artigos removidos do site)")
        else:
            # Estimativa abaixo do que o banco já tem: subestimou (ex.: site limitou o acesso no meio
            # da leitura). O banco vira o piso.
            warnings.append(f"Medição do site ({site}) abaixo dos artigos próprios já no banco "
                            f"({cov['articles']}): usado o número do banco")
            site = cov['articles']

    if site is not None:
        to_analyze = max(0, site - done)
        not_discovered = max(0, site - cov['articles'])
        progress = min(100.0, 100.0 * done / site) if site else 100.0
    else:
        # Sem o tamanho do site, só dá para contar o que o banco já conhece
        to_analyze, not_discovered, progress = cov['errors'] + cov['queued'], None, None

    remaining = estimated_emails(to_analyze, avg) or 0
    if blocked:
        situation = 'bloqueado'
    elif measured:
        situation = 'extraivel'
    else:
        situation = 'falha_medicao' if est is not None else 'nao_medido'

    return {
        'journal': journal,
        'est': est,
        'details': details,
        'warnings': warnings,
        'situation': situation,
        'situation_label': SITUATION_LABELS[situation],
        'blocked_by': blocked,
        'articles_site': site,
        'site_exact': site_exact,
        'articles_db': cov['articles'],
        'analyzed': cov['analyzed'],
        'no_pdf': cov['no_pdf'],
        'errors': cov['errors'],
        'queued': cov['queued'],
        'not_discovered': not_discovered,
        'to_analyze': to_analyze,
        'progress': progress,
        'emails_found': cov['emails_found'],
        'emails_unique': cov['emails_unique'],
        'emails_valid': cov['emails_valid'],
        'emails_per_article': cov['emails_found'] / cov['analyzed'] if cov['analyzed'] else None,
        'emails_expected': estimated_emails(site, avg),
        'emails_to_extract': 0 if blocked else remaining,
        'emails_lost_antibot': remaining if blocked else 0,
        'emails_lost_no_pdf': estimated_emails(cov['no_pdf'], avg) or 0,
    }


def report_totals(rows, coverage):
    def total(key):
        return sum(r[key] or 0 for r in rows)

    measured = [r for r in rows if r['articles_site'] is not None]
    site = sum(r['articles_site'] for r in measured)
    done = sum(r['analyzed'] + r['no_pdf'] for r in measured)
    totals = {key: total(key) for key in (
        'articles_site', 'articles_db', 'analyzed', 'no_pdf', 'errors', 'queued', 'not_discovered',
        'to_analyze', 'emails_found', 'emails_expected', 'emails_to_extract', 'emails_lost_antibot',
        'emails_lost_no_pdf')}
    totals.update(
        progress=min(100.0, 100.0 * done / site) if site else None,
        # Distintos entre todas as revistas: um e-mail presente em várias conta uma vez
        emails_unique=coverage['unique_total'],
        emails_valid=coverage['valid_total'],
        journals=len(rows),
        measured=len(measured),
        blocked=sum(1 for r in rows if r['situation'] == 'bloqueado'),
        failed=sum(1 for r in rows if r['situation'] == 'falha_medicao'),
        missing=sum(1 for r in rows if r['situation'] == 'nao_medido'),
        blocked_articles=sum(r['to_analyze'] for r in rows if r['situation'] == 'bloqueado'),
    )
    totals['emails_lost'] = totals['emails_lost_antibot'] + totals['emails_lost_no_pdf']
    return totals


def build_report(session, refresh=False):
    avg = system_emails_per_pdf(session, max_age=0 if refresh else 600)
    coverage = db_coverage(session, max_age=0 if refresh else 300)
    estimates = latest_estimates(session)
    rows = [report_row(j, estimates.get(j.id), coverage['journals'].get(j.id, EMPTY_COVERAGE), avg)
            for j in session.query(Journal).order_by(Journal.name).all()]
    # Maior potencial no topo; sem medição por último
    rows.sort(key=lambda r: (r['emails_expected'] is None, -(r['emails_expected'] or 0), r['journal'].name))
    return {'rows': rows, 'totals': report_totals(rows, coverage), 'avg': avg,
            'coverage_at': coverage['computed_at']}


CSV_COLUMNS = [
    ('id', lambda r: r['journal'].id),
    ('periodico', lambda r: r['journal'].name),
    ('qualis', lambda r: (r['journal'].qualis or '').strip().upper()),
    ('plataforma', lambda r: r['est'].platform if r['est'] else r['journal'].source_type),
    ('ativo', lambda r: 'sim' if r['journal'].active else 'nao'),
    ('situacao', lambda r: r['situation_label']),
    ('bloqueio_antibot', lambda r: r['blocked_by'] or ''),
    ('metodo_medicao', lambda r: r['est'].method if r['est'] else ''),
    ('precisao', lambda r: '' if r['articles_site'] is None else ('exato' if r['site_exact'] else 'estimado')),
    ('confianca', lambda r: r['est'].confidence if r['est'] else ''),
    ('medido_em', lambda r: r['est'].measured_at.strftime('%Y-%m-%d %H:%M') if r['est'] else ''),
    ('edicoes_site', lambda r: r['est'].issues_count if r['est'] else None),
    ('artigos_site', lambda r: r['articles_site']),
    ('artigos_no_banco', lambda r: r['articles_db']),
    ('artigos_analisados', lambda r: r['analyzed']),
    ('artigos_sem_pdf', lambda r: r['no_pdf']),
    ('artigos_com_erro', lambda r: r['errors']),
    ('artigos_na_fila', lambda r: r['queued']),
    ('artigos_nao_descobertos', lambda r: r['not_discovered']),
    ('artigos_a_analisar', lambda r: r['to_analyze']),
    ('progresso_pct', lambda r: None if r['progress'] is None else round(r['progress'], 1)),
    ('emails_encontrados', lambda r: r['emails_found']),
    ('emails_unicos', lambda r: r['emails_unique']),
    ('emails_validos', lambda r: r['emails_valid']),
    ('media_emails_por_artigo', lambda r: None if r['emails_per_article'] is None
        else round(r['emails_per_article'], 2)),
    ('emails_supostos', lambda r: r['emails_expected']),
    ('emails_supostos_a_extrair', lambda r: r['emails_to_extract']),
    ('emails_nao_extraiveis_antibot', lambda r: r['emails_lost_antibot']),
    ('emails_nao_extraiveis_sem_pdf', lambda r: r['emails_lost_no_pdf']),
    ('avisos', lambda r: ' | '.join(r['warnings'])),
    ('url', lambda r: r['journal'].url),
]

TOTAL_KEYS = {
    'artigos_site': 'articles_site', 'artigos_no_banco': 'articles_db', 'artigos_analisados': 'analyzed',
    'artigos_sem_pdf': 'no_pdf', 'artigos_com_erro': 'errors', 'artigos_na_fila': 'queued',
    'artigos_nao_descobertos': 'not_discovered', 'artigos_a_analisar': 'to_analyze',
    'emails_encontrados': 'emails_found', 'emails_unicos': 'emails_unique', 'emails_validos': 'emails_valid',
    'emails_supostos': 'emails_expected', 'emails_supostos_a_extrair': 'emails_to_extract',
    'emails_nao_extraiveis_antibot': 'emails_lost_antibot', 'emails_nao_extraiveis_sem_pdf': 'emails_lost_no_pdf',
}


def report_csv(report):
    """CSV (UTF-8 com BOM, como os outros exports do painel) com uma linha por periódico e o TOTAL."""
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow([name for name, _ in CSV_COLUMNS])
    for row in report['rows']:
        writer.writerow(['' if v is None else v for v in (fn(row) for _, fn in CSV_COLUMNS)])

    totals = report['totals']
    total_row = {name: totals[key] for name, key in TOTAL_KEYS.items()}
    total_row.update(
        periodico='TOTAL',
        situacao=f"{totals['measured']} medidos, {totals['blocked']} bloqueados por anti-bot, "
                 f"{totals['failed']} falhas, {totals['missing']} sem medição",
        progresso_pct=None if totals['progress'] is None else round(totals['progress'], 1),
        media_emails_por_artigo=round(report['avg']['mean_capped'], 2) if report['avg'] else None,
        avisos='emails_unicos/validos do TOTAL são distintos entre todas as revistas; '
               'media_emails_por_artigo do TOTAL é a média do sistema usada nas estimativas',
    )
    writer.writerow(['' if total_row.get(name) is None else total_row[name] for name, _ in CSV_COLUMNS])
    return out.getvalue()
