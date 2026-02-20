import sys
import os
import pandas as pd
from tqdm import tqdm

# Ensure we can import processor
sys.path.append(os.getcwd())

from processor import Processor
from db_manager import DBManager

def reprocess_failed_emails(csv_report_path):
    if not os.path.exists(csv_report_path):
        print(f"Report file {csv_report_path} not found.")
        return

    print(f"Loading report from {csv_report_path}...")
    df = pd.read_csv(csv_report_path)
    
    # Check columns
    if 'Path' not in df.columns:
        print("Column 'Path' not found in CSV.")
        return

    db_manager = DBManager()
    processor = Processor(db_manager=db_manager)
    
    total_files = len(df)
    print(f"Found {total_files} files to reprocess.")
    
    recovered_count = 0
    total_emails_found = 0
    
    # We only want to run 'extract_emails' logic again, but Processor structure 
    # is a bit tied to 'process_all'. We can reuse 'extract_text_from_pdf' and 'extract_emails'.
    
    for index, row in tqdm(df.iterrows(), total=total_files, desc="Reprocessing"):
        pdf_path = row['Path']
        
        if not os.path.exists(pdf_path):
            # print(f"File {pdf_path} does not exist. Skipping.")
            continue
            
        # 1. Extract text (using all available methods)
        text = processor.extract_text_from_pdf(pdf_path)
        
        # 2. Extract emails with NEW regex
        emails = processor.extract_emails(text)
        
        if emails:
            # print(f"Found emails in {pdf_path}: {emails}")
            
            # 3. Update Database
            # Check if file exists in DB
            file_record = db_manager.get_file_by_path(pdf_path)
            
            if not file_record:
                # File not in DB. we must create the structure to store the emails.
                # 1. Get/Create "Recovered" Journal
                journal_name = row.get('Journal', 'Unknown Recovered')
                if journal_name == 'Unknown' or pd.isna(journal_name):
                    journal_name = 'Recovered Items'
                    
                journal = db_manager.get_or_create_journal(name=journal_name, url=f"http://local/recovered/{journal_name.replace(' ', '_')}")
                
                # 2. Get/Create Dummy Edition
                edition = db_manager.get_or_create_edition(journal.id, url=f"http://local/recovered/{journal.id}/edition_1", title="Recovered Edition")
                
                # 3. Create Article (use filename as title/url placeholder)
                filename = os.path.basename(pdf_path)
                article_title = f"Recovered: {filename}"
                article_url = f"file://{filename}"
                
                # Create authors list from emails (best guess name)
                authors_list = []
                for email in emails:
                    user_part = email.split('@')[0]
                    authors_list.append({'name': user_part, 'email': email})

                article = db_manager.add_article(
                     edition_id=edition.id,
                     title=article_title,
                     url=article_url,
                     authors_list=authors_list
                )
                
                # 4. Create File
                file_record = db_manager.add_file(
                    article_id=article.id,
                    local_path=pdf_path,
                    file_type='pdf'
                )
                
                recovered_count += 1
                total_emails_found += len(emails)
                db_manager.record_analysis_log(file_record.id, 'reprocess_email_fix', status='created_and_fixed')
            else:
                # File exists, proceed with update
                if file_record.article:
                    article_url = file_record.article.url
                    updated = db_manager.update_article_emails(article_url, emails)
                    
                    if updated > 0:
                        recovered_count += 1
                        total_emails_found += len(emails)
                        db_manager.record_analysis_log(file_record.id, 'reprocess_email_fix', status='fixed_emails_found')
                pass
                
    print("\n--- Reprocessing Summary ---")
    print(f"Total files processed: {total_files}")
    print(f"Files with recovered emails linked to Authors: {recovered_count}")
    print(f"Total author emails updated: {total_emails_found}")
    
    db_manager.close()

if __name__ == "__main__":
    reprocess_failed_emails('no_emails_report.csv')
