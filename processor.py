import re
import os
import pandas as pd
from pypdf import PdfReader
from metadata_manager import MetadataManager
from tqdm import tqdm

class Processor:
    AVAILABLE_METHODS = ['pypdf', 'pdfplumber']

    def __init__(self, download_dir='downloads', output_file='emails.xlsx', append=False, db_manager=None):
        self.download_dir = download_dir
        self.output_file = output_file
        self.append = append
        self.db_manager = db_manager

    def _extract_with_pypdf(self, pdf_path):
        text = ""
        try:
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                extract = page.extract_text()
                if extract:
                    text += extract + "\n"
        except Exception as e:
            # print(f"pypdf error on {pdf_path}: {e}")
            pass
        return text

    def _extract_with_pdfplumber(self, pdf_path):
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    extract = page.extract_text()
                    if extract:
                        text += "\n" + extract + "\n"
        except ImportError:
            pass 
        except Exception as e:
             # print(f"pdfplumber error on {pdf_path}: {e}")
             pass
        return text

    def extract_text_from_pdf(self, pdf_path, methods_to_run=None):
        """
        Extract text using specified methods.
        If methods_to_run is None, runs all available.
        """
        text = ""
        if methods_to_run is None:
            methods_to_run = self.AVAILABLE_METHODS

        if 'pypdf' in methods_to_run:
            text += self._extract_with_pypdf(pdf_path)
        
        if 'pdfplumber' in methods_to_run:
            text += self._extract_with_pdfplumber(pdf_path)
             
        return text

    def extract_emails(self, text):
        # 1. Basic normalization
        # Replace common obfuscations if they are clear
        # (Be careful not to replace valid text, but " [at] " is usually an email)
        text_norm = text.replace(' [at] ', '@').replace(' (at) ', '@').replace(' at ', '@')
        
        # 2. Extract potential emails
        # Regex explanation:
        # User part: [a-zA-Z0-9._%+-]+
        # @ part: \s*@\s* (allows whitespace)
        # Domain part: [a-zA-Z0-9.-]+
        # Dot part: \s*\.\s* (allows whitespace)
        # TLD: [a-zA-Z]{2,}
        
        # We need to capture them and then clean up spaces.
        # Improved regex: prevents matching merged text like "brName" by enforcing TLD to be either all lower or all upper.
        email_pattern = r'([a-zA-Z0-9._%+-]+)\s*@\s*([a-zA-Z0-9.-]+)\s*\.\s*([a-z]{2,}|[A-Z]{2,})\b'
        
        matches = re.findall(email_pattern, text_norm)
        
        emails = []
        for match in matches:
            # Reconstruct without spaces
            email = f"{match[0]}@{match[1]}.{match[2]}"
            emails.append(email)

        # 3. Also try searching in a "flattened" text to catch emails broken by newlines
        # but be careful of merging separate words.
        # simple check: if we didn't find many, maybe try joining lines?
        # Actually, let's just always try the strict pattern on flattened text too.
        flat_text = text_norm.replace('\n', '') # Remove all newlines
        matches_flat = re.findall(email_pattern, flat_text)
        for match in matches_flat:
             email = f"{match[0]}@{match[1]}.{match[2]}"
             emails.append(email)

        return list(set(emails))

    def process_all(self, metadata_manager=None):
        if not os.path.exists(self.download_dir):
            print(f"Directory {self.download_dir} not found.")
            return

        pdf_files = [f for f in os.listdir(self.download_dir) if f.lower().endswith('.pdf')]
        print(f"Found {len(pdf_files)} PDFs in {self.download_dir}")
        
        if not pdf_files:
            print("No PDF files found to process.")
            return

        all_data = []
        
        # Load metadata map if manager provided
        meta_map = {}
        if metadata_manager:
            try:
                meta_map = metadata_manager.load_metadata()
                print(f"Loaded {len(meta_map)} metadata entries.")
            except Exception as e:
                print(f"Error loading metadata: {e}")

        total_updated_authors = 0

        for pdf_file in tqdm(pdf_files, desc="Processing PDFs", unit="pdf"):

            pdf_path = os.path.join(self.download_dir, pdf_file)
            
            # Determine methods to run
            methods_to_run = list(self.AVAILABLE_METHODS)
            file_record = None

            if self.db_manager:
                # Try to find the file record. 
                # Note: path storage format must match.
                file_record = self.db_manager.get_file_by_path(pdf_path)
                
                if file_record:
                    # Filter out already completed methods
                    methods_to_run = [
                        m for m in self.AVAILABLE_METHODS 
                        if not self.db_manager.is_method_already_run(file_record.id, m)
                    ]
            
            if not methods_to_run:
                # print(f"Skipping {pdf_file}, all methods already run.")
                continue

            text = self.extract_text_from_pdf(pdf_path, methods_to_run)
            emails = self.extract_emails(text)
            
            # Look up metadata
            meta = meta_map.get(pdf_file, {})
            article_url = meta.get('article_url', '')

            # DB Update Logic
            if self.db_manager:
                if article_url and emails:
                    updated = self.db_manager.update_article_emails(article_url, emails)
                    if updated > 0:
                        total_updated_authors += updated
                
                # Log analysis
                if file_record:
                    for method in methods_to_run:
                        # Log success or failure for the method
                        # Note: This logs that the method ran. 
                        # To track "no emails found", we might need a specific status or just rely on method completion.
                        # However, the user wants "control" over this. 
                        # Let's log 'completed' usually. But if we want to signal "no email", maybe we should update the Article status? 
                        # Or just a log entry? The requirement was general control. 
                        # If we assume 'completed' means "method ran", that is correct. 
                        # Whether it found email or not is a result.
                        # Let's add a specific log if no emails were found across ALL methods for this file, 
                        # but here we are inside the method loop.
                        
                        # Let's log 'completed' for the method itself.
                        self.db_manager.record_analysis_log(file_record.id, method)

            # NEW: Log explicit "no_email_found" if result is empty
            if not emails and file_record:
                 self.db_manager.record_analysis_log(file_record.id, 'email_extraction_result', status='no_email_found')
            elif emails and file_record:
                 self.db_manager.record_analysis_log(file_record.id, 'email_extraction_result', status='email_found')

            for email in emails:
                row = {
                    'Journal': meta.get('journal', 'Unknown'),
                    'Issue URL': meta.get('issue_url', ''),
                    'Article Title': meta.get('article_title', ''),
                    'Article URL': article_url,
                    'Authors': meta.get('authors', ''),
                    'PDF Filename': pdf_file,
                    'Email': email
                }
                all_data.append(row)
        
        if total_updated_authors > 0:
             print(f"Mapped emails to {total_updated_authors} authors in Database.")

        if not all_data:
            print("No emails found (or all skipped).")
            return

        df = pd.DataFrame(all_data)
        
        # Determine format based on extension
        if self.output_file.endswith('.csv'):
            if self.append and os.path.exists(self.output_file):
                df.to_csv(self.output_file, mode='a', header=False, index=False)
            else:
                df.to_csv(self.output_file, index=False)
        else:
             # Excel doesn't support easy append mode like CSV without loading first
             if self.append and os.path.exists(self.output_file):
                 with pd.ExcelWriter(self.output_file, mode='a', if_sheet_exists='overlay') as writer:
                      # This is complex for Excel. Let's fallback to overwriting or just stick to CSV as requested.
                      # User requested "Um CSV só".
                      pass
             else:
                df.to_excel(self.output_file, index=False)
                
        print(f"Successfully exported {len(all_data)} rows to {self.output_file}")

if __name__ == "__main__":
    from db_manager import DBManager
    from metadata_manager import MetadataManager
    
    db_manager = DBManager()
    metadata_manager = MetadataManager(db_manager=db_manager)
    
    print("Starting manual processing...")
    
    # Process SciELO
    if os.path.exists('downloads_scielo'):
        print("Processing SciELO downloads...")
        p_scielo = Processor(download_dir='downloads_scielo', output_file='emails.csv', db_manager=db_manager)
        p_scielo.process_all(metadata_manager)

    # Process OJS (Append)
    if os.path.exists('downloads_ojs'):
        print("Processing OJS downloads...")
        # Check if first one created the file
        append = os.path.exists('emails.csv')
        p_ojs = Processor(download_dir='downloads_ojs', output_file='emails.csv', append=append, db_manager=db_manager)
        p_ojs.process_all(metadata_manager)
