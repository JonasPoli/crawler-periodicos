import json
import os
import sys
import time
from scielo_crawler import SciELOCrawler
from ojs_crawler import OJSCrawler
from metadata_manager import MetadataManager
from processor import Processor
from db_manager import DBManager
from database import Journal
import argparse
from tqdm import tqdm

def main():
    # Initialize DB Manager
    db_manager = DBManager()

    parser = argparse.ArgumentParser(description="Crawler Orchestrator")
    parser.add_argument('--force', action='store_true', help="Force re-download of existing items")
    args = parser.parse_args()
    
    force_mode = args.force
    
    # Load journals from DB instead of JSON file directly
    print("Loading journals from Database...")
    journals_db = db_manager.session.query(Journal).filter_by(active=True).all()
    
    if not journals_db:
        print("No journals found in Database. Please run populate_db.py first.")
        return

    # Initialize Metadata Manager with DB support
    metadata_manager = MetadataManager(db_manager=db_manager)
    
    print(f"--- STARTING SUPER CRAWLER ---")
    print(f"Loaded {len(journals_db)} journals from database.")

    # Outer bar for Journals
    journal_pbar = tqdm(journals_db, desc="Journals", unit="journal", colour='green')
    
    for j_db in journal_pbar:
        journal_pbar.set_description(f"Processing {j_db.name[:30]}...")
        
        if not force_mode and db_manager.is_journal_completed(j_db.id):
            # tqdm.write(f"Skipping completed journal: {j_db.name}")
            continue

        # Validation
        if not j_db.url or 'TODO' in j_db.url or not j_db.url.startswith('http'):
            tqdm.write(f"Skipping {j_db.name} - Invalid or Missing URL: {j_db.url}")
            continue

        try:
            crawler = None
            if j_db.source_type == 'scielo':
                crawler = SciELOCrawler(j_db.url, j_db.name, download_dir='downloads_scielo', metadata_manager=metadata_manager, db_manager=db_manager, force=force_mode)
            elif j_db.source_type == 'ojs':
                crawler = OJSCrawler(j_db.url, j_db.name, download_dir='downloads_ojs', metadata_manager=metadata_manager, db_manager=db_manager, force=force_mode)

            else:
                tqdm.write(f"Unknown type {j_db.source_type} for {j_db.name}")
                continue
                
            # Update last crawled time
            db_manager.update_journal_last_crawled(j_db.id)

            # fetch issues
            # tqdm.write(f"Fetching issues for {j_db.name}...")
            try:
                issues = crawler.get_all_issues()
                # tqdm.write(f"Found {len(issues)} issues/archives.")
                
                # Inner bar for Issues
                issue_pbar = tqdm(issues, desc=f"Issues ({j_db.acronym or j_db.name[:10]})", unit="issue", leave=False, colour='cyan')
                
                for issue_url in issue_pbar:
                    # check if issue is completed
                    if not force_mode and db_manager.is_edition_completed(issue_url):
                        # tqdm.write(f"Skipping completed issue: {issue_url}")
                        continue

                    try:
                        crawler.process_issue(issue_url)
                        edition = db_manager.get_or_create_edition(j_db.id, issue_url)
                        db_manager.mark_edition_completed(edition.id)
                        
                    except Exception as exc_issue:
                         tqdm.write(f"Error processing issue {issue_url}: {exc_issue}")
                         
            except Exception as exc_journal_init:
                 tqdm.write(f"Error fetching journal index for {j_db.name}: {exc_journal_init}")
            
            # If we reached here without critical error, consider journal iteration 'completed' for now.
            # (Though individual issues might have failed, we crawled the index).
            db_manager.mark_journal_completed(j_db.id)
                 
        except KeyboardInterrupt:
            tqdm.write("\nCaught KeyboardInterrupt. Stopping gracefully...")
            sys.exit(0)
        except Exception as e:
            tqdm.write(f"CRITICAL ERROR processing journal {j_db.name}: {e}")
            continue

    print("\n--- Crawling Finished. Starting Processing (Creating Super CSV) ---")
    
    try:
        # Process SciELO
        if os.path.exists('downloads_scielo'):
            print("Processing SciELO downloads...")
            p_scielo = Processor(download_dir='downloads_scielo', output_file='emails.csv', db_manager=db_manager)
            p_scielo.process_all(metadata_manager)

        # Process OJS (Append)
        if os.path.exists('downloads_ojs'):
            print("Processing OJS downloads...")
            p_ojs = Processor(download_dir='downloads_ojs', output_file='emails.csv', append=True, db_manager=db_manager)
            p_ojs.process_all(metadata_manager)
            
        print("\nSUCCESS: Super CSV 'emails.csv' created.")
        
    except Exception as e:
        print(f"Error during post-processing: {e}")

if __name__ == "__main__":
    main()
