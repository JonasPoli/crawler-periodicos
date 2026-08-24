import os
import json
import time
import uuid
import platform
import datetime
from sqlalchemy import func
from database import get_session, ExecutionRun, ErrorLog, Journal, Edition, Article, CapturedEmail

# Ensure logs and runs directory exist
RUNS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'runs')
os.makedirs(RUNS_DIR, exist_ok=True)

class TelemetryManager:
    """
    Manages process execution telemetry, benchmarks, error tracking,
    crash detection, and automated report generation.
    """

    @staticmethod
    def start_run(mode='super', journal_id=None, workers=2, recovered_tasks=0):
        session = get_session()
        now = datetime.datetime.utcnow()

        # 1. Detect any unclosed / crashed runs from previous machine boot/crash
        open_runs = session.query(ExecutionRun).filter(ExecutionRun.status == 'running').all()
        for prev in open_runs:
            prev.status = 'crashed'
            prev.end_time = prev.start_time + datetime.timedelta(seconds=prev.duration_seconds or 1)
            prev.notes = (prev.notes or '') + f" [Terminated abruptly / Crash detected on next startup. Recovered {recovered_tasks} tasks]"
            
            crash_err = ErrorLog(
                run_id=prev.run_id,
                phase='system',
                journal_id=prev.journal_id,
                error_type='SystemCrashOrForceKill',
                message='Process was running when machine shut down or crashed abruptly.',
                details=f'Detected on {now.isoformat()}. Orphan tasks recovered: {recovered_tasks}',
                created_at=now
            )
            session.add(crash_err)

        # 2. Create new run ID
        run_id = f"run_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        sys_info = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "machine": platform.machine()
        }

        new_run = ExecutionRun(
            run_id=run_id,
            mode=mode,
            journal_id=journal_id,
            status='running',
            workers_count=workers,
            start_time=now,
            crash_recovered_tasks=recovered_tasks,
            system_info=json.dumps(sys_info),
            notes=f"Started {mode} mode with {workers} workers." + (f" Recovered {recovered_tasks} stuck tasks." if recovered_tasks else "")
        )

        session.add(new_run)
        session.commit()
        session.close()

        return run_id

    @staticmethod
    def record_error(run_id, phase, error_type, message, details=None, journal_id=None, article_id=None):
        """Record an error event to the database."""
        session = get_session()
        try:
            err = ErrorLog(
                run_id=run_id,
                phase=phase,
                journal_id=journal_id,
                article_id=article_id,
                error_type=error_type,
                message=str(message)[:1000],
                details=str(details)[:4000] if details else None,
                created_at=datetime.datetime.utcnow()
            )
            session.add(err)
            session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def checkpoint(run_id, journal_id=None):
        """Update live execution stats based on current database state."""
        session = get_session()
        try:
            run = session.query(ExecutionRun).filter_by(run_id=run_id).first()
            if not run or run.status != 'running':
                return

            now = datetime.datetime.utcnow()
            duration_s = max(1, int((now - run.start_time).total_seconds()))
            run.duration_seconds = duration_s
            mins = max(0.05, duration_s / 60.0)

            # Query scoped stats
            if journal_id:
                editions_done = session.query(Edition).filter(Edition.journal_id == journal_id, Edition.status == 'completed').count()
                articles_done = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id, Article.status == 'completed').count()
                articles_all = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id).count()
                emails_all = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id).scalar() or 0
                emails_valid = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id, CapturedEmail.verification_status == 'VALID').scalar() or 0
                emails_invalid = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id, CapturedEmail.verification_status == 'INVALID').scalar() or 0
            else:
                editions_done = session.query(Edition).filter(Edition.status == 'completed').count()
                articles_done = session.query(Article).filter(Article.status == 'completed').count()
                articles_all = session.query(Article).count()
                emails_all = session.query(func.count(func.distinct(CapturedEmail.email))).scalar() or 0
                emails_valid = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'VALID').scalar() or 0
                emails_invalid = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'INVALID').scalar() or 0

            run.editions_processed = editions_done
            run.articles_crawled = articles_all
            run.pdfs_downloaded = articles_done
            run.emails_extracted = emails_all
            run.emails_valid = emails_valid
            run.emails_invalid = emails_invalid

            # Speeds
            run.speed_articles_per_min = f"{round(articles_done / mins, 1)}"
            run.speed_pdfs_per_min = f"{round(articles_done / mins, 1)}"
            run.speed_emails_per_min = f"{round(emails_all / mins, 1)}"

            session.commit()
        except Exception as e:
            session.rollback()
        finally:
            session.close()

    @staticmethod
    def finish_run(run_id, status='completed', journal_id=None, notes=None):
        session = get_session()
        try:
            run = session.query(ExecutionRun).filter_by(run_id=run_id).first()
            if not run:
                return None

            now = datetime.datetime.utcnow()
            run.status = status
            run.end_time = now
            duration_s = max(1, int((now - run.start_time).total_seconds()))
            run.duration_seconds = duration_s
            mins = max(0.05, duration_s / 60.0)

            # Final metrics
            if journal_id:
                editions_done = session.query(Edition).filter(Edition.journal_id == journal_id, Edition.status == 'completed').count()
                articles_done = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id, Article.status == 'completed').count()
                articles_all = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id).count()
                emails_all = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id).scalar() or 0
                emails_valid = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id, CapturedEmail.verification_status == 'VALID').scalar() or 0
                emails_invalid = session.query(func.count(func.distinct(CapturedEmail.email))).join(Article).join(Edition).filter(Edition.journal_id == journal_id, CapturedEmail.verification_status == 'INVALID').scalar() or 0
            else:
                editions_done = session.query(Edition).filter(Edition.status == 'completed').count()
                articles_done = session.query(Article).filter(Article.status == 'completed').count()
                articles_all = session.query(Article).count()
                emails_all = session.query(func.count(func.distinct(CapturedEmail.email))).scalar() or 0
                emails_valid = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'VALID').scalar() or 0
                emails_invalid = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'INVALID').scalar() or 0

            run.editions_processed = editions_done
            run.articles_crawled = articles_all
            run.pdfs_downloaded = articles_done
            run.emails_extracted = emails_all
            run.emails_valid = emails_valid
            run.emails_invalid = emails_invalid

            run.speed_articles_per_min = f"{round(articles_done / mins, 1)}"
            run.speed_pdfs_per_min = f"{round(articles_done / mins, 1)}"
            run.speed_emails_per_min = f"{round(emails_all / mins, 1)}"
            if notes:
                run.notes = ((run.notes + "\n") if run.notes else "") + notes

            # Errors summary
            errors = session.query(ErrorLog).filter_by(run_id=run_id).all()
            error_count = len(errors)

            session.commit()

            # Build report data
            summary = {
                "run_id": run.run_id,
                "mode": run.mode,
                "journal_id": run.journal_id,
                "status": run.status,
                "workers": run.workers_count,
                "start_time": run.start_time.isoformat(),
                "end_time": run.end_time.isoformat() if run.end_time else None,
                "duration_seconds": run.duration_seconds,
                "duration_formatted": f"{run.duration_seconds // 60}m {run.duration_seconds % 60}s",
                "editions_processed": run.editions_processed,
                "articles_crawled": run.articles_crawled,
                "pdfs_downloaded": run.pdfs_downloaded,
                "emails_extracted_distinct": run.emails_extracted,
                "emails_valid": run.emails_valid,
                "emails_invalid": run.emails_invalid,
                "speed_articles_per_min": run.speed_articles_per_min,
                "speed_emails_per_min": run.speed_emails_per_min,
                "recovered_crashes": run.crash_recovered_tasks,
                "error_count": error_count,
                "recent_errors": [{"type": e.error_type, "phase": e.phase, "msg": e.message} for e in errors[-10:]]
            }

            # Export JSON
            json_path = os.path.join(RUNS_DIR, f"{run_id}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            # Export Markdown report
            md_path = os.path.join(RUNS_DIR, f"{run_id}.md")
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"# Relatório de Execução: `{run_id}`\n\n")
                f.write(f"- **Modo**: `{run.mode}`\n")
                f.write(f"- **Periódico ID**: `{run.journal_id if run.journal_id else 'Todos'}`\n")
                f.write(f"- **Status Final**: **{run.status.upper()}**\n")
                f.write(f"- **Duração Total**: `{summary['duration_formatted']}` ({run.duration_seconds}s)\n")
                f.write(f"- **Workers**: `{run.workers_count}`\n\n")
                f.write("## 📊 Métricas de Produtividade\n\n")
                f.write(f"| Métrica | Quantidade | Velocidade |\n")
                f.write(f"|---|---|---|\n")
                f.write(f"| Edições Concluídas | {run.editions_processed} | - |\n")
                f.write(f"| Artigos / PDFs Processados | {run.pdfs_downloaded} | {run.speed_articles_per_min} / min |\n")
                f.write(f"| E-mails Únicos Capturados | {run.emails_extracted} | {run.speed_emails_per_min} / min |\n")
                f.write(f"| E-mails Válidos | {run.emails_valid} | - |\n")
                f.write(f"| E-mails Inválidos | {run.emails_invalid} | - |\n\n")
                f.write("## ⚠️ Erros e Ocorrências\n\n")
                f.write(f"- **Total de Erros Registrados**: {error_count}\n")
                f.write(f"- **Tarefas Recuperadas de Crash**: {run.crash_recovered_tasks}\n\n")
                if errors:
                    f.write("### Últimos Erros Registrados:\n\n")
                    for e in errors[-10:]:
                        f.write(f"- `[{e.phase}]` **{e.error_type}**: {e.message}\n")
                else:
                    f.write("✅ *Nenhum erro crítico registrado nesta execução.*\n")

            return summary

        except Exception as e:
            session.rollback()
            return None
        finally:
            session.close()
