import json
import os
import json
import os
import threading
from database import Journal

class MetadataManager:
    def __init__(self, output_file='metadata.jsonl', db_manager=None):
        self.output_file = output_file
        self.lock = threading.Lock()
        self.db_manager = db_manager
        # Ensure file exists
        if not os.path.exists(output_file):
            with open(output_file, 'w') as f:
                pass

    def save_metadata(self, metadata):
        """
        Save a single metadata record to JSONL AND Database.
        Thread-safe.
        """
        with self.lock:
            # 1. Save to JSONL
            with open(self.output_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(metadata, ensure_ascii=False) + '\n')
            
            # 2. Save to Database
            if self.db_manager:
                try:
                    self._save_to_db(metadata)
                except Exception as e:
                    print(f"Error saving to DB: {e}")

    def _save_to_db(self, meta):
        # Extract fields
        journal_name = meta.get('journal')
        issue_url = meta.get('issue_url')
        article_title = meta.get('article_title')
        article_url = meta.get('article_url')
        authors_str = meta.get('authors')
        pdf_url = meta.get('pdf_url')
        pdf_filename = meta.get('pdf_filename')

        if not journal_name or not issue_url:
            return

        # Get Journal
        # We assume journal exists since we populated it, but safe to get_or_create
        # We don't have the journal URL here easily unless we pass it, but name should be enough if unique
        # Ideally, we would have the journal object or ID. 
        # But let's look up by name.
        # Check if we can get the journal object from DBManager using name
        # Note: get_or_create_journal requires URL. 
        # Let's add a method to get valid journal by name in DBManager or just query here.
        
        journal = self.db_manager.session.query(Journal).filter_by(name=journal_name).first()
        if not journal:
            # Fallback or log error? If it's not in DB, we can't link it.
            # Maybe the populate script didn't run or name mismatch?
            # Let's try to query by partial match or just skip.
            return

        # Get/Create Edition
        edition = self.db_manager.get_or_create_edition(journal.id, issue_url)
        
        # Prepare authors
        authors_list = []
        if authors_str and authors_str != "Unknown Authors":
            for name in authors_str.split(','):
                authors_list.append({'name': name.strip()})

        # Add Article
        article = self.db_manager.add_article(
            edition_id=edition.id,
            title=article_title,
            url=article_url,
            authors_list=authors_list
        )

        # Add File
        if pdf_filename:
            # Assuming processor/crawler saves to 'downloads_scielo' or 'downloads_ojs' based on simple logic
            # but here we just get the filename.
            # Let's just store the filename/path relative to download dir.
            self.db_manager.add_file(
                article_id=article.id,
                local_path=pdf_filename,
                url=pdf_url,
                file_type='pdf'
            )

    def load_metadata(self):
        """
        Load all metadata into a dictionary keyed by PDF filename.
        """
        metadata_map = {}
        if not os.path.exists(self.output_file):
            return metadata_map
            
        with open(self.output_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    if 'pdf_filename' in data:
                        metadata_map[data['pdf_filename']] = data
                except json.JSONDecodeError:
                    pass
        return metadata_map

