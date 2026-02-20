import time
import sys
import os
import uuid
import datetime
import pandas as pd
from db_manager import DBManager
from metadata_manager import MetadataManager
from processor import Processor

def log(worker_id, message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [Processor {worker_id}] {message}")

def run_processor_worker(worker_id, stop_event=None):
    log(worker_id, "Started.")
    
    db_manager = DBManager()
    metadata_manager = MetadataManager(db_manager=db_manager)
    
    processor = Processor(db_manager=db_manager)
    
    empty_cycles = 0
    
    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            article = db_manager.get_next_article_for_processing(worker_id)
            
            if not article:
                empty_cycles += 1
                if empty_cycles > 900: # 30 minutes (2s sleep * 900 = 1800s)
                     log(worker_id, "Idle for 30 minutes. Exiting.")
                     break
                time.sleep(2)
                continue
            
            empty_cycles = 0
            
            try:
                # log(worker_id, f"Processing {article.title[:30]}...")
                start_time = time.time()
                
                pdf_file = None
                for f in article.files:
                    if f.file_type == 'pdf':
                        pdf_file = f
                        break
                
                local_path = None
                if pdf_file and pdf_file.local_path:
                    local_path = pdf_file.local_path
                
                if not local_path or not os.path.exists(local_path):
                     log(worker_id, f"WARNING: File path not found for Article {article.id}. Skipping.")
                     article.status = 'error_nofile'
                     article.worker_id = None
                     db_manager.session.commit()
                     continue
                
                # Extract
                text = processor.extract_text_from_pdf(local_path)
                emails = processor.extract_emails(text)
                
                duration = time.time() - start_time
                
                # Save emails
                if emails:
                    log(worker_id, f"EXTRACTED: {len(emails)} emails from Article {article.id} ({duration:.2f}s)")
                    for email in emails:
                        db_manager.add_captured_email(article.id, email)
                else:
                    log(worker_id, f"NO EMAILS: Article {article.id} ({duration:.2f}s)")
                    
                # Mark completed
                article.status = 'completed'
                article.worker_id = None
                article.lock_time = None
                db_manager.session.commit()
                
            except Exception as e:
                log(worker_id, f"ERROR processing {article.id}: {e}")
                try:
                    article.worker_id = None
                    article.status = 'error_processing'
                    db_manager.session.commit()
                except:
                    db_manager.session.rollback()

    except KeyboardInterrupt:
        log(worker_id, "Stopping...")
    finally:
        db_manager.close()

if __name__ == "__main__":
    run_processor_worker(str(uuid.uuid4()))
