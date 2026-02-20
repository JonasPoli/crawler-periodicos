import os
import pandas as pd
from tqdm import tqdm
from db_manager import DBManager

def generate_missing_report(emails_csv='emails.csv', output_report='no_emails_report.csv'):
    # 1. Load successful extractions
    print(f"Loading successful extractions from {emails_csv}...")
    try:
        # Read only the PDF Filename column to save memory if file is huge
        df_emails = pd.read_csv(emails_csv, usecols=['PDF Filename'])
        successful_pdfs = set(df_emails['PDF Filename'].dropna().unique())
        print(f"Found {len(successful_pdfs)} unique PDFs with emails.")
    except Exception as e:
        print(f"Error reading {emails_csv}: {e}")
        return

    # 2. Scan directories for all PDFs
    scan_dirs = ['downloads', 'downloads_ojs', 'downloads_scielo']
    all_pdfs = []
    
    print("Scanning directories for PDFs...")
    for d in scan_dirs:
        if not os.path.exists(d):
            continue
            
        for root, dirs, files in os.walk(d):
            for f in files:
                if f.lower().endswith('.pdf'):
                    # Store tuple (filename, full_path, dir_source)
                    all_pdfs.append((f, os.path.join(root, f), d))

    print(f"Found {len(all_pdfs)} total PDFs on disk.")

    # 3. specific logic for scielo vs ojs if names match directly
    # Ideally filename is unique enough. 
    
    missing_data = []
    
    # Initialize DB for Metadata lookup (optional but helpful for context)
    db = DBManager()
    
    for filename, full_path, source_dir in tqdm(all_pdfs, desc="Checking PDFs"):
        if filename not in successful_pdfs:
            # It's missing!
            file_size = os.path.getsize(full_path)
            
            # Try to get DB info
            journal_name = "Unknown"
            file_record = db.get_file_by_path(full_path)
            if file_record and file_record.article and file_record.article.edition and file_record.article.edition.journal:
                journal_name = file_record.article.edition.journal.name
            
            missing_data.append({
                'PDF Filename': filename,
                'Path': full_path,
                'Source Directory': source_dir,
                'Size (bytes)': file_size,
                'Journal': journal_name
            })
            
    db.close()

    if not missing_data:
        print("Great! No missing emails found (all PDFs on disk have emails in CSV).")
        return

    # 4. Export Report
    df_missing = pd.DataFrame(missing_data)
    df_missing.to_csv(output_report, index=False)
    
    print(f"Report generated: {output_report}")
    print(f"Total PDFs with NO emails: {len(df_missing)}")

if __name__ == "__main__":
    generate_missing_report()
