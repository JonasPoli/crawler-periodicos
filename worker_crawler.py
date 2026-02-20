import time
import sys
import os
import uuid
import datetime
from db_manager import DBManager
from metadata_manager import MetadataManager
from scielo_crawler import SciELOCrawler
from ojs_crawler import OJSCrawler

def log(worker_id, message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [Worker {worker_id}] {message}")

def run_crawler_worker(worker_id, stop_event=None):
    log(worker_id, "Started.")
    
    db_manager = DBManager()
    metadata_manager = MetadataManager(db_manager=db_manager)
    
    crawlers = {} 
    
    empty_cycles = 0
    max_empty_cycles = 300 # 10 minutes idle
    
    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            # PRIORITY 1: Process Pending Editions (Discover Articles)
            edition = db_manager.get_next_pending_edition(worker_id)
            
            if edition:
                empty_cycles = 0
                try:
                    journal = edition.journal
                    if not journal:
                         log(worker_id, f"ERROR: Edition {edition.id} has no journal. Skipping.")
                         db_manager.mark_edition_completed(edition.id)
                         continue

                    log(worker_id, f"Discovering Edition {edition.id} for {journal.name} ({journal.source_type})...")
                    start_time = time.time()
                    
                    crawler_key = f"{journal.source_type}_{journal.id}"
                    crawler = crawlers.get(crawler_key)
                    if not crawler:
                        if journal.source_type == 'scielo':
                            crawler = SciELOCrawler(journal.url, journal.name, download_dir='downloads_scielo', 
                                                  db_manager=db_manager)
                        elif journal.source_type == 'ojs':
                            crawler = OJSCrawler(journal.url, journal.name, download_dir='downloads_ojs', 
                                               db_manager=db_manager)
                        else:
                            log(worker_id, f"ERROR: Unknown source type {journal.source_type}")
                            db_manager.mark_edition_completed(edition.id) 
                            continue
                        crawlers[crawler_key] = crawler

                    # Discover Articles in this Edition
                    try:
                        article_urls = crawler.get_article_urls(edition.url)
                        
                        duration = time.time() - start_time
                        if article_urls:
                            log(worker_id, f"SUCCESS: Found {len(article_urls)} articles in Edition {edition.id} (Took {duration:.2f}s).")
                            for art_url in article_urls:
                                 # Add to DB (status='found')
                                 db_manager.add_article(edition.id, "Unknown Title", art_url)
                        else:
                            log(worker_id, f"WARNING: No articles found in Edition {edition.id} (Took {duration:.2f}s). URL: {edition.url}")

                        # Mark completed
                        db_manager.mark_edition_completed(edition.id)
                    except Exception as e:
                        log(worker_id, f"ERROR in get_article_urls for {edition.url}: {e}")
                        # Mark completed anyway to avoid infinite loop on bad URL
                        db_manager.mark_edition_completed(edition.id)

                except Exception as e:
                    log(worker_id, f"CRITICAL ERROR processing edition {edition.id}: {e}")
                    try:
                        db_manager.mark_edition_completed(edition.id)
                    except:
                        db_manager.session.rollback()

                continue # Loop again to prefer Editions until exhausted

            # PRIORITY 2: Process Pending Articles (Download PDF)
            article = db_manager.get_next_pending_article_for_crawling(worker_id)
            
            if article:
                empty_cycles = 0
                try:
                    # Get Journal info
                    journal = article.edition.journal
                    if not journal:
                        log(worker_id, f"ERROR: Article {article.id} has no journal. Mark as error.")
                        article.status = 'error_metadata'
                        article.worker_id = None
                        db_manager.session.commit()
                        continue

                    # Get/Create Crawler
                    crawler_key = f"{journal.source_type}_{journal.id}"
                    crawler = crawlers.get(crawler_key)
                    if not crawler:
                        if journal.source_type == 'scielo':
                            crawler = SciELOCrawler(journal.url, journal.name, download_dir='downloads_scielo', 
                                                  db_manager=db_manager)
                        elif journal.source_type == 'ojs':
                            crawler = OJSCrawler(journal.url, journal.name, download_dir='downloads_ojs', 
                                               db_manager=db_manager)
                        else:
                            continue
                        crawlers[crawler_key] = crawler

                    # Fetch Metadata & Download
                    # log(worker_id, f"Downloading Article {article.id}...")
                    start_time = time.time()
                    
                    meta = crawler.fetch_article_metadata(article.url)
                    
                    if meta:
                        pdf_url = meta.get('pdf_url')
                        filename = meta.get('pdf_filename')
                        
                        if pdf_url:
                            local_path = crawler.download_pdf_direct(pdf_url, filename)
                            duration = time.time() - start_time
                            
                            if local_path:
                                if metadata_manager: metadata_manager.save_metadata(meta)
                                db_manager.add_file(
                                    article_id=article.id,
                                    local_path=local_path,
                                    file_type='pdf',
                                    url=pdf_url
                                )
                                article.status = 'downloaded'
                                article.worker_id = None
                                article.lock_time = None
                                db_manager.session.commit()
                                log(worker_id, f"DOWNLOADED: Article {article.id} ({duration:.2f}s) - {filename}")
                            else:
                                log(worker_id, f"FAILED DOWNLOAD: {article.url} ({duration:.2f}s)")
                                article.status = 'error_download'
                                article.worker_id = None
                                db_manager.session.commit()
                        else:
                            log(worker_id, f"NO PDF: {article.url}")
                            article.status = 'no_pdf'
                            article.worker_id = None
                            db_manager.session.commit()
                    else:
                        log(worker_id, f"NO METADATA: {article.url}")
                        article.status = 'error_metadata'
                        article.worker_id = None
                        db_manager.session.commit()

                except Exception as e:
                    log(worker_id, f"ERROR processing article {article.id}: {e}")
                    try:
                        article.worker_id = None
                        article.status = 'error_exception'
                        db_manager.session.commit()
                    except:
                        db_manager.session.rollback()
                
                continue

            # No work found
            empty_cycles += 1
            if empty_cycles > max_empty_cycles: 
                 log(worker_id, "Idle for too long. Exiting.")
                 break
            time.sleep(2)
            
    except KeyboardInterrupt:
        log(worker_id, "Stopping...")
    finally:
        db_manager.close()

if __name__ == "__main__":
    run_crawler_worker(str(uuid.uuid4()))
