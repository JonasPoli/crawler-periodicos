import argparse
import multiprocessing
import time
import sys
import os
import threading
from db_manager import DBManager
from worker_crawler import run_crawler_worker
from worker_processor import run_processor_worker
from worker_verifier import run_verifier_worker
from database import Journal, Article, Edition, CapturedEmail
from tqdm import tqdm

def run_discovery_phase(journal_id=None):
    print("--- STARTING DISCOVERY PHASE ---")
    db_manager = DBManager()
    
    query = db_manager.session.query(Journal).filter_by(active=True)
    if journal_id:
        query = query.filter(Journal.id == journal_id)
        
    journals = query.order_by(Journal.id.desc()).all()
    print(f"Loaded {len(journals)} journals.")
    
    from ojs_crawler import OJSCrawler
    from scielo_crawler import SciELOCrawler
    from metadata_manager import MetadataManager
    
    # metadata_manager = MetadataManager(db_manager=db_manager)
    
    # Progress bar for journals
    pbar = tqdm(total=len(journals), desc="Discovery (Journals)", unit="journal")
    
    for journal in journals:
        # print(f"Discovering {journal.name} ({journal.source_type})...")
        pbar.set_postfix_str(f"Current: {journal.name[:20]}...")
        
        try:
            crawler = None
            if journal.source_type == 'scielo':
                crawler = SciELOCrawler(journal.url, journal.name, db_manager=db_manager)
            elif journal.source_type == 'ojs':
                crawler = OJSCrawler(journal.url, journal.name, db_manager=db_manager)
            else:
                pbar.update(1)
                continue

            db_manager.update_journal_last_crawled(journal.id)

            try:
                issues = crawler.get_all_issues()
                
                for issue_url in issues:
                    edition = db_manager.get_or_create_edition(journal.id, issue_url)
                    
                    if db_manager.is_edition_completed(issue_url):
                        continue
                    
                    # COMMENTED OUT: Sequential scraping is too slow and blocks everything.
                    # We let the workers handle this via get_next_pending_edition().
                    # try:
                    #     article_urls = crawler.get_article_urls(issue_url)
                    #     for art_url in article_urls:
                    #          db_manager.add_article(edition.id, "Unknown Title", art_url)
                    #     
                    #     db_manager.mark_edition_completed(edition.id)
                    #     
                    # except Exception as e:
                    #     pass
            except Exception as e:
                pass

        except Exception as e:
             pass
        
        pbar.update(1)
    
    pbar.close()
    db_manager.close()
    print("--- DISCOVERY FINISHED ---")

def monitor_progress(stop_event, journal_id=None):
    """
    Monitor DB and update progress bars.
    When journal_id is provided, all counts are restricted to that journal.
    """
    db_manager = DBManager()
    session = db_manager.session

    label_suffix = f" [Journal #{journal_id}]" if journal_id else ""

    pbar_crawl = tqdm(desc=f"Crawling (Articles){label_suffix}", unit="article")
    pbar_process = tqdm(desc=f"Processing (PDFs){label_suffix}", unit="pdf")
    pbar_verify = tqdm(desc=f"Verifying (Emails){label_suffix}", unit="email")

    try:
        while not stop_event.is_set():
            try:
                # --- Build base queries scoped to journal if needed ---
                article_base = session.query(Article).join(Edition).join(Journal)
                email_base = session.query(CapturedEmail).join(Article).join(Edition).join(Journal)

                if journal_id:
                    article_base = article_base.filter(Journal.id == journal_id)
                    email_base = email_base.filter(Journal.id == journal_id)

                # Crawling
                c_pending = article_base.filter(
                    Article.status.in_(['found', 'processing_crawling'])
                ).count()
                c_completed = article_base.filter(
                    Article.status.in_(['downloaded', 'completed', 'no_pdf',
                                        'error_download', 'error_metadata', 'error_exception'])
                ).count()

                # Processing
                p_pending = article_base.filter(
                    Article.status.in_(['downloaded', 'processing_extraction'])
                ).count()
                p_completed = article_base.filter(
                    Article.status.in_(['completed'])
                ).count()

                # Verifying
                v_pending = email_base.filter(
                    CapturedEmail.verification_status.in_(['PENDING', 'PROCESSING'])
                ).count()
                v_completed = email_base.filter(
                    CapturedEmail.verification_status.in_(['VALID', 'INVALID'])
                ).count()

                pbar_crawl.n = c_completed
                pbar_crawl.total = c_completed + c_pending
                pbar_crawl.refresh()

                pbar_process.n = p_completed
                pbar_process.total = p_completed + p_pending
                pbar_process.set_postfix_str(f"Queue: {p_pending}")
                pbar_process.refresh()

                pbar_verify.n = v_completed
                pbar_verify.total = v_completed + v_pending
                pbar_verify.refresh()

                session.commit()

            except Exception:
                pass

            time.sleep(2)

    except:
        pass
    finally:
        pbar_crawl.close()
        pbar_process.close()
        pbar_verify.close()
        db_manager.close()

def reprocess_zero_email_journals(workers):
    """
    Detect journals that ended with zero captured emails and run the
    full pipeline again for them.
    """
    db_manager = DBManager()
    zero_email_journals = db_manager.get_journals_with_no_emails()
    if not zero_email_journals:
        print("No journals with zero emails – nothing to re-process.")
        return

    print(f"Re-processing {len(zero_email_journals)} journal(s) with zero emails.")
    # Use standard logging
    import logging
    os.makedirs('logs', exist_ok=True)
    logging.basicConfig(
        filename='logs/reprocess.log',
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True
    )
    
    for journal in zero_email_journals:
        logging.info(f"Re-processing journal {journal.id} ({journal.name}) – zero emails")
        db_manager.reset_journal_for_rerun(journal.id)
        
    db_manager.close()

    # Run discovery only for the selected journals
    # (the existing discovery phase already loops over all active journals,
    #  but because we cleared `last_crawled_at` it will pick them up again)
    # Note: reprocess_zero_email_journals doesn't currently support journal_id filtering 
    # but it could be added if needed. For now, it processes all zero-email journals.
    run_discovery_phase()

    # Run the workers again – same as the normal super flow
    stop_event = multiprocessing.Event()
    processes = []
    
    for i in range(workers):
        p = multiprocessing.Process(target=run_crawler_worker, args=(f"Craw-Rep-{i+1}", stop_event))
        p.start()
        processes.append(p)
        
    for i in range(workers):
        p = multiprocessing.Process(target=run_processor_worker, args=(f"Proc-Rep-{i+1}", stop_event))
        p.start()
        processes.append(p)
        
    for i in range(workers):
        p = multiprocessing.Process(target=run_verifier_worker, args=(f"Veri-Rep-{i+1}", stop_event))
        p.start()
        processes.append(p)

    try:
        monitor_progress(stop_event)
    except KeyboardInterrupt:
        print("\nStopping RE-PROCESS...")
        stop_event.set()
        for p in processes:
            p.join()
        print("Re-process done.")

def run_parallel_workers(target_func, num_workers=4, label="Worker", journal_id=None):
    processes = []
    stop_event = multiprocessing.Event()
    
    print(f"Starting {num_workers} {label}s... Press Ctrl+C to stop.")
    
    for i in range(num_workers):
        worker_id = f"{label}-{i+1}"
        p = multiprocessing.Process(target=target_func, args=(worker_id, stop_event, journal_id))
        p.start()
        processes.append(p)
    
    # Monitor thread
    monitor_stop = threading.Event()
    # monitor_thread = threading.Thread(target=monitor_progress, args=(monitor_stop,))
    # monitor_thread.start()
    
    try:
        # Simple Loop to check liveness
        while True:
            alive_count = sum(1 for p in processes if p.is_alive())
            if alive_count == 0:
                print(f"All {label}s finished.")
                break
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\nStopping {label}s...")
        stop_event.set()
        monitor_stop.set()
        for p in processes:
            p.join()
        print("Stopped.")

def main():
    parser = argparse.ArgumentParser(
        description="Fast Parallel Crawler", 
        epilog="To STOP the process, use Ctrl+C in the terminal. If stuck, run 'pkill -f run_fast.py'"
    )
    parser.add_argument('mode', choices=['discover', 'crawl', 'process', 'verify', 'reset', 'all', 'super'], help="Mode of operation")
    parser.add_argument('--workers', type=int, default=2, help="Number of parallel workers per phase")
    parser.add_argument('--id', type=int, default=None, help="Specific Journal ID to process")
    
    args = parser.parse_args()
    
    db_manager = DBManager()
    
    if args.mode == 'reset':
        print("Resetting stuck tasks...")
        db_manager.reset_stuck_tasks()
        
    elif args.mode == 'discover':
        run_discovery_phase(args.id)
        
    elif args.mode == 'crawl':
        run_parallel_workers(run_crawler_worker, args.workers, "Crawler", args.id)
        
    elif args.mode == 'process':
        run_parallel_workers(run_processor_worker, args.workers, "Processor", args.id)
        
    elif args.mode == 'verify':
        run_parallel_workers(run_verifier_worker, args.workers, "Verifier", args.id)
        
    elif args.mode == 'super':
        # The FULL SUPER PROCESS
        # This is tricky because we want parallelism ACROSS phases or SEQUENTIAL phases?
        # The user request implies "Process Journals -> Process Editions/Articles -> Process PDF -> Verify"
        # Since 'process' needs 'downloaded' PDFs, and 'verify' needs 'extracted' emails, we can run them all in parallel if the queue is fed.
        
        print("Starting SUPER PROCESS (All workers parallel)...")
        print("To STOP: Press Ctrl+C or run 'pkill -f run_fast.py'")
        
        stop_event = multiprocessing.Event()
        processes = []
        
        # 1. Discovery (can generate work while others run?)
        # Discovery is usually fast enough to run first.
        run_discovery_phase(args.id)
        
        # 2. Start Workers
        # Crawlers
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_crawler_worker, args=(f"Craw-{i+1}", stop_event, args.id))
            p.start()
            processes.append(p)
            
        # Processors
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_processor_worker, args=(f"Proc-{i+1}", stop_event, args.id))
            p.start()
            processes.append(p)
            
        # Verifiers
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_verifier_worker, args=(f"Veri-{i+1}", stop_event, args.id))
            p.start()
            processes.append(p)
            
        # Monitor (runs in background thread so we can also watch worker processes)
        monitor_thread = threading.Thread(
            target=monitor_progress,
            args=(stop_event,),
            kwargs={"journal_id": args.id},
            daemon=True
        )
        monitor_thread.start()

        try:
            # Main thread: wait until all worker processes finish naturally or queues are empty
            db_checker = DBManager()
            empty_streak = 0
            while True:
                alive = [p for p in processes if p.is_alive()]
                if not alive:
                    print("\nAll workers finished.")
                    stop_event.set()
                    break
                
                session = db_checker.session
                article_base = session.query(Article).join(Edition).join(Journal)
                email_base = session.query(CapturedEmail).join(Article).join(Edition).join(Journal)
                edition_base = session.query(Edition).join(Journal)
                
                if args.id:
                    article_base = article_base.filter(Journal.id == args.id)
                    email_base = email_base.filter(Journal.id == args.id)
                    edition_base = edition_base.filter(Journal.id == args.id)
                
                pending_editions = edition_base.filter(Edition.status.in_(['found', 'processing'])).count()
                pending_crawl = article_base.filter(Article.status.in_(['found', 'processing_crawling'])).count()
                pending_proc = article_base.filter(Article.status.in_(['downloaded', 'processing_extraction'])).count()
                pending_verify = email_base.filter(CapturedEmail.verification_status.in_(['PENDING', 'PROCESSING'])).count()
                
                if pending_editions == 0 and pending_crawl == 0 and pending_proc == 0 and pending_verify == 0:
                    empty_streak += 1
                else:
                    empty_streak = 0
                
                if empty_streak >= 8:
                    print("\nAll queues are empty. Stopping workers...")
                    stop_event.set()
                    break
                
                session.commit()
                time.sleep(2)
            db_checker.close()

        except KeyboardInterrupt:
            print("\nStopping SUPER PROCESS...")
            stop_event.set()

        # Wait for workers and monitor thread
        for p in processes:
            p.join()
        monitor_thread.join(timeout=5)
        print("Done.")

        # ----- NEW STEP: Re-process journals with zero emails -----
        # Only run if we actually completed the main super process and weren't interrupted early
        # (we check if all processes finished with exit code 0)
        all_ok = all(p.exitcode == 0 for p in processes)
        if all_ok:
            print("\n--- Phase 2: RE-VERIFY ZERO-EMAIL JOURNALS ---")
            reprocess_zero_email_journals(args.workers)


if __name__ == "__main__":
    multiprocessing.set_start_method('spawn', force=True)
    main()
