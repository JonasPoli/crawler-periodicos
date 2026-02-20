import argparse
import multiprocessing
import time
import sys
import threading
from db_manager import DBManager
from worker_crawler import run_crawler_worker
from worker_processor import run_processor_worker
from worker_verifier import run_verifier_worker
from database import Journal, Article, Edition, CapturedEmail
from tqdm import tqdm

def run_discovery_phase():
    print("--- STARTING DISCOVERY PHASE ---")
    db_manager = DBManager()
    
    journals = db_manager.session.query(Journal).filter_by(active=True).all()
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
    print("--- DISCOVERY FINISHED ---")

def monitor_progress(stop_event):
    """
    Monitor DB and update progress bars.
    """
    db_manager = DBManager()
    
    # Get initial counts
    # We might need total counts.
    # Total Articles to Crawl = Status Found + Processing
    # Total Articles to Process = Status Downloaded + Processing Extraction
    # Total Emails to Verify = Status PENDING + PROCESSING
    
    # This is tricky because the totals change as we discover.
    # We will just show "Pending" counts.
    
    pbar_crawl = tqdm(desc="Crawling (Articles Pending)", unit="article")
    pbar_process = tqdm(desc="Processing (PDFs Pending)", unit="pdf")
    pbar_verify = tqdm(desc="Verifying (Emails Pending)", unit="email")
    
    try:
        while not stop_event.is_set():
            session = db_manager.session
            
            # Crawling
            c_pending = session.query(Article).filter(Article.status.in_(['found', 'processing_crawling'])).count()
            c_completed = session.query(Article).filter(Article.status.in_(['downloaded', 'completed'])).count() # approximate
            
            # Processing
            p_pending = session.query(Article).filter(Article.status.in_(['downloaded', 'processing_extraction'])).count()
            
            # Verifying
            v_pending = session.query(CapturedEmail).filter(CapturedEmail.verification_status.in_(['PENDING', 'PROCESSING'])).count()
            v_completed = session.query(CapturedEmail).filter(CapturedEmail.verification_status.in_(['VALID', 'INVALID'])).count()
            
            pbar_crawl.n = c_completed
            pbar_crawl.total = c_completed + c_pending
            pbar_crawl.refresh()
            
            pbar_process.n = 0 # No good "total" tracked easily for processed count without heavy query
            pbar_process.set_postfix_str(f"Queue: {p_pending}")
            pbar_process.refresh()
            
            pbar_verify.n = v_completed
            pbar_verify.total = v_completed + v_pending
            pbar_verify.refresh()
            
            time.sleep(2)
            
    except:
        pass
    finally:
        pbar_crawl.close()
        pbar_process.close()
        pbar_verify.close()
        db_manager.close()

def run_parallel_workers(target_func, num_workers=4, label="Worker"):
    processes = []
    stop_event = multiprocessing.Event()
    
    print(f"Starting {num_workers} {label}s... Press Ctrl+C to stop.")
    
    for i in range(num_workers):
        worker_id = f"{label}-{i+1}"
        p = multiprocessing.Process(target=target_func, args=(worker_id, stop_event))
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
    parser.add_argument('--workers', type=int, default=4, help="Number of parallel workers per phase")
    
    args = parser.parse_args()
    
    db_manager = DBManager()
    
    if args.mode == 'reset':
        print("Resetting stuck tasks...")
        db_manager.reset_stuck_tasks()
        
    elif args.mode == 'discover':
        run_discovery_phase()
        
    elif args.mode == 'crawl':
        run_parallel_workers(run_crawler_worker, args.workers, "Crawler")
        
    elif args.mode == 'process':
        run_parallel_workers(run_processor_worker, args.workers, "Processor")
        
    elif args.mode == 'verify':
        run_parallel_workers(run_verifier_worker, args.workers, "Verifier")
        
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
        run_discovery_phase()
        
        # 2. Start Workers
        # Crawlers
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_crawler_worker, args=(f"Craw-{i+1}", stop_event))
            p.start()
            processes.append(p)
            
        # Processors
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_processor_worker, args=(f"Proc-{i+1}", stop_event))
            p.start()
            processes.append(p)
            
        # Verifiers
        for i in range(args.workers):
            p = multiprocessing.Process(target=run_verifier_worker, args=(f"Veri-{i+1}", stop_event))
            p.start()
            processes.append(p)
            
        # Monitor
        try:
            # We can run a fancy dashboard here using curses or just tqdm monitoring loop in main thread
            monitor_progress(stop_event)
            
        except KeyboardInterrupt:
            print("\nStopping SUPER PROCESS...")
            stop_event.set()
            for p in processes:
                p.join()
            print("Done.")

if __name__ == "__main__":
    multiprocessing.set_start_method('spawn', force=True)
    main()
