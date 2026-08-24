import os
import sys
import argparse
import datetime
from sqlalchemy import func, desc
from database import get_session, ExecutionRun, ErrorLog, Journal, Article, CapturedEmail

def list_runs(limit=15):
    session = get_session()
    runs = session.query(ExecutionRun).order_by(desc(ExecutionRun.start_time)).limit(limit).all()
    if not runs:
        print("Nenhuma execução registrada no banco de telemetria.")
        session.close()
        return

    print("=" * 115)
    print(f"{'RUN ID':<26} | {'INÍCIO (UTC)':<16} | {'MODO':<7} | {'PERIÓDICO':<9} | {'STATUS':<11} | {'DURAÇÃO':<9} | {'ARTS/M':<7} | {'EMAILS/M':<8} | {'EMAILS':<10}")
    print("=" * 115)
    for r in runs:
        status_display = r.status.upper()
        if r.status == 'completed':
            status_tag = f"\033[92m{status_display:<11}\033[0m"
        elif r.status == 'crashed':
            status_tag = f"\033[91m{status_display:<11}\033[0m"
        elif r.status == 'running':
            status_tag = f"\033[93m{status_display:<11}\033[0m"
        else:
            status_tag = f"{status_display:<11}"

        j_id = str(r.journal_id) if r.journal_id else 'Todos'
        dur = f"{r.duration_seconds // 60}m {r.duration_seconds % 60}s" if r.duration_seconds else "-"
        start_fmt = r.start_time.strftime('%d/%m %H:%M:%S') if r.start_time else "-"
        emails_stat = f"{r.emails_valid}/{r.emails_extracted}" if r.emails_extracted else "0"

        print(f"{r.run_id:<26} | {start_fmt:<16} | {r.mode:<7} | {j_id:<9} | {status_tag} | {dur:<9} | {str(r.speed_articles_per_min):<7} | {str(r.speed_emails_per_min):<8} | {emails_stat:<10}")
    print("=" * 115)
    session.close()

def show_run_details(run_id=None):
    session = get_session()
    if run_id:
        run = session.query(ExecutionRun).filter_by(run_id=run_id).first()
    else:
        run = session.query(ExecutionRun).order_by(desc(ExecutionRun.start_time)).first()

    if not run:
        print(f"Execução '{run_id or 'última'}' não encontrada.")
        session.close()
        return

    print("\n" + "=" * 80)
    print(f"DETALHES DA EXECUÇÃO: {run.run_id}")
    print("=" * 80)
    print(f"Modo:                {run.mode}")
    print(f"Periódico ID:        {run.journal_id if run.journal_id else 'Todos'}")
    print(f"Status:              {run.status.upper()}")
    print(f"Workers:             {run.workers_count}")
    print(f"Início:              {run.start_time.strftime('%Y-%m-%d %H:%M:%S') if run.start_time else '-'}")
    print(f"Fim:                 {run.end_time.strftime('%Y-%m-%d %H:%M:%S') if run.end_time else '-'}")
    print(f"Duração:             {run.duration_seconds // 60}m {run.duration_seconds % 60}s ({run.duration_seconds}s)")
    print("-" * 80)
    print("MÉTRICAS:")
    print(f"  - Edições Concluídas:     {run.editions_processed}")
    print(f"  - Artigos / PDFs:         {run.pdfs_downloaded} ({run.speed_articles_per_min} / min)")
    print(f"  - E-mails Únicos:         {run.emails_extracted} ({run.speed_emails_per_min} / min)")
    print(f"  - E-mails Válidos:        {run.emails_valid}")
    print(f"  - E-mails Inválidos:      {run.emails_invalid}")
    print(f"  - Tarefas Recuperadas:    {run.crash_recovered_tasks}")
    print("-" * 80)
    
    if run.notes:
        print(f"Notas: {run.notes}")

    errors = session.query(ErrorLog).filter_by(run_id=run.run_id).order_by(desc(ErrorLog.created_at)).all()
    print(f"\nERROS REGISTRADOS ({len(errors)}):")
    if errors:
        for e in errors[:15]:
            print(f"  [{e.phase.upper()}] {e.error_type}: {e.message}")
            if e.details:
                print(f"    -> Detalhes: {e.details[:120]}...")
    else:
        print("  Nenhum erro registrado.")
    print("=" * 80 + "\n")
    session.close()

def show_errors_summary():
    session = get_session()
    errors_summary = session.query(
        ErrorLog.error_type,
        ErrorLog.phase,
        func.count(ErrorLog.id)
    ).group_by(ErrorLog.error_type, ErrorLog.phase).order_by(desc(func.count(ErrorLog.id))).all()

    print("\n" + "=" * 70)
    print("RESUMO HISTÓRICO DE ERROS POR TIPO E FASE")
    print("=" * 70)
    if not errors_summary:
        print("Nenhum erro registrado no histórico.")
    else:
        for err_type, phase, count in errors_summary:
            print(f"- [{phase:<12}] {err_type:<30} : {count} ocorrências")
    print("=" * 70 + "\n")
    session.close()

def show_insights():
    session = get_session()
    print("\n" + "=" * 80)
    print("💡 INSIGHTS E DIAGNÓSTICO DE PERFORMANCE")
    print("=" * 80)

    # 1. Total runs and crash rate
    total_runs = session.query(ExecutionRun).count()
    crashed_runs = session.query(ExecutionRun).filter(ExecutionRun.status == 'crashed').count()
    completed_runs = session.query(ExecutionRun).filter(ExecutionRun.status == 'completed').count()

    print(f"1. Estabilidade do Sistema:")
    print(f"   - Total de Execuções: {total_runs}")
    print(f"   - Concluídas com Sucesso: {completed_runs}")
    print(f"   - Crashes / Desligamentos Detectados: {crashed_runs}")
    if total_runs > 0 and crashed_runs > 0:
        print(f"   ⚠️ Taxa de Crash: {round((crashed_runs/total_runs)*100, 1)}%. O auto-recovery automático garante retomada sem perda de dados.")

    # 2. Fastest and average speed
    runs_with_dur = session.query(ExecutionRun).filter(ExecutionRun.duration_seconds > 10).all()
    if runs_with_dur:
        speeds_art = [float(r.speed_articles_per_min) for r in runs_with_dur if r.speed_articles_per_min and float(r.speed_articles_per_min) > 0]
        speeds_email = [float(r.speed_emails_per_min) for r in runs_with_dur if r.speed_emails_per_min and float(r.speed_emails_per_min) > 0]
        if speeds_art:
            print(f"\n2. Throughput Médio:")
            print(f"   - Velocidade Média de Artigos: {round(sum(speeds_art)/len(speeds_art), 1)} artigos/min")
        if speeds_email:
            print(f"   - Velocidade Média de E-mails: {round(sum(speeds_email)/len(speeds_email), 1)} e-mails/min")

    # 3. Top frequent errors
    top_errors = session.query(
        ErrorLog.error_type,
        func.count(ErrorLog.id)
    ).group_by(ErrorLog.error_type).order_by(desc(func.count(ErrorLog.id))).limit(3).all()

    if top_errors:
        print(f"\n3. Principais Pontos de Atenção:")
        for err_type, cnt in top_errors:
            print(f"   - {err_type}: {cnt} vezes registradas.")

    print("=" * 80 + "\n")
    session.close()

def main():
    parser = argparse.ArgumentParser(description="Ferramenta de Auditoria e Diagnóstico de Execuções do Crawler")
    parser.add_argument('--limit', type=int, default=15, help="Número de execuções a exibir")
    parser.add_argument('--last', action='store_true', help="Exibir detalhes da última execução")
    parser.add_argument('--id', type=str, default=None, help="Exibir detalhes de uma execução específica pelo Run ID")
    parser.add_argument('--errors', action='store_true', help="Exibir resumo consolidado de erros")
    parser.add_argument('--insights', action='store_true', help="Gerar análise e insights de performance")

    args = parser.parse_args()

    if args.last or args.id:
        show_run_details(args.id)
    elif args.errors:
        show_errors_summary()
    elif args.insights:
        show_insights()
    else:
        list_runs(args.limit)

if __name__ == "__main__":
    main()
