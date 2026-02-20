from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from database import Journal, Edition, Article, Author, File, FileAnalysisLog, CapturedEmail, get_session, init_db
import datetime

class DBManager:
    def __init__(self, engine=None):
        if engine:
            self.session = get_session(engine)
        else:
            # Auto init if not provided
            self.engine = init_db()
            self.session = get_session(self.engine)

    def close(self):
        self.session.close()

    # --- Journals ---
    def get_or_create_journal(self, name, url, source_type='ojs', acronym=None, issn=None):
        """
        Get existing journal by URL or Name, or create a new one.
        """
        # Try finding by URL first as it's more specific
        journal = self.session.query(Journal).filter_by(url=url).first()
        if not journal:
             # Try name? Names can be duplicate or slightly different. URL is safer. 
             # But let's check name if URL not found just in case.
             journal = self.session.query(Journal).filter_by(name=name).first()
        
        if not journal:
            journal = Journal(
                name=name,
                url=url,
                source_type=source_type,
                acronym=acronym,
                issn=issn
            )
            self.session.add(journal)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                # Race condition or duplicate, try fetching again
                journal = self.session.query(Journal).filter_by(url=url).first()
        else:
            # Update fields if missing?
            if not journal.acronym and acronym:
                journal.acronym = acronym
            if not journal.issn and issn:
                journal.issn = issn
            self.session.commit()
            
        return journal

    def update_journal_last_crawled(self, journal_id):
        journal = self.session.query(Journal).get(journal_id)
        if journal:
            journal.last_crawled_at = datetime.datetime.utcnow()
            self.session.commit()

    def is_journal_completed(self, journal_id):
        journal = self.session.query(Journal).get(journal_id)
        return journal and journal.status == 'completed'

    def mark_journal_completed(self, journal_id):
        journal = self.session.query(Journal).get(journal_id)
        if journal:
            journal.status = 'completed'
            self.session.commit()

    # --- Editions ---
    def get_or_create_edition(self, journal_id, url, title=None, volume=None, number=None, year=None):
        edition = self.session.query(Edition).filter_by(url=url).first()
        if not edition:
            edition = Edition(
                journal_id=journal_id,
                url=url,
                title=title,
                volume=volume,
                number=number,
                year=year
            )
            self.session.add(edition)
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                edition = self.session.query(Edition).filter_by(url=url).first()
        return edition

    def mark_edition_completed(self, edition_id):
        edition = self.session.query(Edition).get(edition_id)
        if edition:
            edition.status = 'completed'
            edition.worker_id = None
            edition.lock_time = None
            self.session.commit()
    
    def is_edition_completed(self, url):
        edition = self.session.query(Edition).filter_by(url=url).first()
        return edition and edition.status == 'completed'

    def get_next_pending_edition(self, worker_id):
        """
        Atomically find and lock an edition for processing.
        """
        # Find one that is pending or found, and NOT locked
        # SQLite doesn't support SELECT ... FOR UPDATE, so we do best effort with check-then-set
        # causing potential race conditions but acceptable for this scale if we handle it.
        # Better: Update status where status='found' LIMIT 1
        
        # We need to find one.
        # Filtering by status='found' (assuming initial state)
        
        try:
            # First, try to find a candidate
            # We filter by journal.active=True as well
            candidate = self.session.query(Edition).join(Journal).filter(
                Journal.active == True,
                Edition.status == 'found', # or 'pending'
                Edition.worker_id == None
            ).first()
            
            if candidate:
                candidate.status = 'processing'
                candidate.worker_id = worker_id
                candidate.lock_time = datetime.datetime.utcnow()
                self.session.commit()
                return candidate
            else:
                return None
        except Exception as e:
            self.session.rollback()
            print(f"Error locking edition: {e}")
            return None

    def reset_stuck_tasks(self, timeout_minutes=30):
        """
        Reset tasks that have been locked for too long.
        """
        limit = datetime.datetime.utcnow() - datetime.timedelta(minutes=timeout_minutes)
        
        # Reset Editions
        num_editions = self.session.query(Edition).filter(
            Edition.status == 'processing',
            Edition.lock_time < limit
        ).update({
            'status': 'found', 
            'worker_id': None, 
            'lock_time': None
        })
        
        # Reset Articles
        num_articles = self.session.query(Article).filter(
            Article.status == 'processing',
            Article.lock_time < limit
        ).update({
            'status': 'downloaded', # Reset to downloaded so it can be picked up by processor? 
                                    # Wait, processor picks up 'downloaded'? 
                                    # If it was processing extraction, it should go back to 'downloaded' or 'found'?
                                    # If it was 'found' and being downloaded, it should go back to 'found'.
                                    # We need to distinguish phases.
                                    # Orchestrator (Crawling) locks Article to download PDF? 
                                    # Actually Orchestrator processes Issue to find Articles.
                                    # Then it downloads PDFs.
                                    # So Orchestrator might lock Article to download it.
                                    # Let's say: 
                                    # Phase 1: Discovery -> Adds Articles with status='found'
                                    # Phase 2: Crawling -> Picks 'found' Article -> 'downloading' -> 'downloaded'
                                    # Phase 3: Processing -> Picks 'downloaded' Article -> 'extracting' -> 'completed'
           'worker_id': None,
           'lock_time': None
        })
        
        # Use simpler logic for now: Just reset 'processing' ones.
        # But we need to know previous state. 
        # For Edition: found -> processing -> completed. Reset to found.
        # For Article (Crawling): found -> processing -> downloaded. Reset to found.
        # For Article (Extraction): downloaded -> processing_extraction -> completed. Reset to downloaded.
        
        # Current DB schema only has 'status'.
        # Let's assume 'processing' tasks go back to 'found' for now, 
        # implying we might re-download. 
        # But wait, we want to separate Crawling (PDF download) and Processing (Text extraction).
        
        self.session.commit()
        if num_editions > 0 or num_articles > 0:
            print(f"Reset {num_editions} stuck editions and {num_articles} stuck articles.")


    # --- Articles ---
    def add_article(self, edition_id, title, url, doi=None, abstract=None, date=None, authors_list=None):
        """
        authors_list: list of dicts {'name': '...', 'email': '...', 'affiliation': '...'}
        """
        # Check if already exists in this edition (by title or URL)
        article = None
        if url:
             article = self.session.query(Article).filter_by(url=url).first()
        
        if not article:
             article = self.session.query(Article).filter_by(edition_id=edition_id, title=title).first()

        if article:
            return article # Already exists

        article = Article(
            edition_id=edition_id,
            title=title,
            url=url,
            doi=doi,
            abstract=abstract,
            published_date=date,
            status='found'
        )
        self.session.add(article)
        self.session.commit()

        # Handle Authors
        if authors_list:
            for auth_data in authors_list:
                self.link_author_to_article(article, auth_data)
        
        return article

    def link_author_to_article(self, article, auth_data):
        name = auth_data.get('name')
        if not name: return

        # Simple author deduplication by name (risky but standard for scraping)
        author = self.session.query(Author).filter_by(name=name).first()
        if not author:
            author = Author(
                name=name,
                email=auth_data.get('email'),
                affiliation=auth_data.get('affiliation')
            )
            self.session.add(author)
            self.session.commit()
        
        if author not in article.authors:
            article.authors.append(author)
            self.session.commit()

    def is_article_completed(self, url):
        if not url: return False
        article = self.session.query(Article).filter_by(url=url).first()
        if not article:
            return False
            
        # Check explicit status
        if article.status == 'completed':
            return True
            
        # Also check if we actually have files for it
        # If we have files, we can consider it effectively downloaded/complete
        if article.files:
            return True
            
        return False

    def mark_article_completed(self, article_id):
        article = self.session.query(Article).get(article_id)
        if article:
            article.status = 'completed'
            self.session.commit()

    def mark_article_completed_by_url(self, url):
        if not url: return
        article = self.session.query(Article).filter_by(url=url).first()
        if article:
            article.status = 'completed'
            self.session.commit()

    def update_article_emails(self, article_url, found_emails):
        """
        Try to match found emails to authors of the article.
        found_emails: list of email strings
        """
        if not article_url or not found_emails:
            return 0

        article = self.session.query(Article).filter_by(url=article_url).first()
        if not article:
            return 0
        
        updated_count = 0
        
        # Pre-process authors who don't have emails
        authors_without_email = [a for a in article.authors if not a.email]
        
        if not authors_without_email:
            return 0
            
        for email in found_emails:
            email_lower = email.lower()
            # Simple heuristic: Split email user part and check if it contains name parts
            user_part = email_lower.split('@')[0]
            
            for author in authors_without_email:
                if author.email: continue # Already matched in this loop
                
                # Check match
                name_parts = author.name.lower().split()
                # If last name in user_part OR (first name in user_part AND len(first_name) > 3)
                # This is weak but better than nothing for unsupervised matching
                match = False
                if len(name_parts) >= 1:
                    last_name = name_parts[-1]
                    if len(last_name) > 2 and last_name in user_part:
                        match = True
                    elif name_parts[0] in user_part and len(name_parts[0]) > 3:
                        match = True
                        
                if match:
                    author.email = email
                    updated_count += 1
                    # print(f" MATCHED: {author.name} -> {email}")
                    break # Assign this email to this author and move to next email
        
        if updated_count > 0:
            self.session.commit()
            
        return updated_count

    def get_next_pending_article_for_crawling(self, worker_id):
        """
        Get next article that needs PDF download. 
        Status: 'found' -> 'processing_crawling'
        """
        try:
            # Optimistic locking loop
            for _ in range(3): # 3 attempts
                # 1. Select candidate
                candidate = self.session.query(Article).filter(
                    Article.status == 'found',
                    Article.worker_id == None
                ).first()
                
                if not candidate:
                    return None
                
                # 2. Attempt to lock
                # Use query().update() directly to ensure atomicity at DB level
                count = self.session.query(Article).filter(
                    Article.id == candidate.id,
                    Article.status == 'found', # Re-verify status
                    Article.worker_id == None  # Re-verify lock
                ).update({
                    'status': 'processing_crawling',
                    'worker_id': worker_id,
                    'lock_time': datetime.datetime.utcnow()
                })
                
                if count == 1:
                    self.session.commit()
                    # Return the object (refresh to get updated state if needed, though we have ID)
                    return candidate
                else:
                    self.session.rollback()
                    # Retry
                    continue
            
            return None
        except Exception as e:
            self.session.rollback()
            print(f"Error locking article: {e}")
            return None

    def get_next_article_for_processing(self, worker_id):
        """
        Get next article that needs extraction. 
        Status: 'downloaded' -> 'processing_extraction'
        """
        try:
            for _ in range(3):
                # 1. Select candidate
                candidate = self.session.query(Article).filter(
                    Article.status == 'downloaded',
                    Article.worker_id == None
                ).first()
                
                if not candidate:
                    return None
                
                # 2. Lock
                count = self.session.query(Article).filter(
                    Article.id == candidate.id,
                    Article.status == 'downloaded',
                    Article.worker_id == None
                ).update({
                    'status': 'processing_extraction',
                    'worker_id': worker_id,
                    'lock_time': datetime.datetime.utcnow()
                })
                
                if count == 1:
                    self.session.commit()
                    return candidate
                else:
                    self.session.rollback()
                    continue
            
            return None
        except Exception as e:
            self.session.rollback()
            print(f"Error locking article for processing: {e}")
            return None

    # --- Captured Emails ---
    def add_captured_email(self, article_id, email):
        """
        Add a captured email to the global list for verification.
        """
        # Lowercase for consistency
        email_normalized = email.strip().lower()
        
        # Check existence
        existing = self.session.query(CapturedEmail).filter_by(
            article_id=article_id,
            email=email_normalized
        ).first()
        
        if not existing:
            captured = CapturedEmail(
                article_id=article_id,
                email=email_normalized,
                verification_status='PENDING'
            )
            self.session.add(captured)
            self.session.commit()
            return captured
        return existing

    def get_next_email_for_verification(self, worker_id):
        """
        Get next PENDING email for verification. 
        """
        try:
            for _ in range(3):
                candidate = self.session.query(CapturedEmail).filter(
                    CapturedEmail.verification_status == 'PENDING',
                    CapturedEmail.worker_id == None
                ).first()
                
                if not candidate:
                    return None
                
                count = self.session.query(CapturedEmail).filter(
                    CapturedEmail.id == candidate.id,
                    CapturedEmail.verification_status == 'PENDING',
                    CapturedEmail.worker_id == None
                ).update({
                    'verification_status': 'PROCESSING',
                    'worker_id': worker_id,
                    'lock_time': datetime.datetime.utcnow()
                })
                
                if count == 1:
                    self.session.commit()
                    return candidate
                else:
                    self.session.rollback()
                    continue
            return None

        except Exception as e:
            self.session.rollback()
            print(f"Error locking email for verification: {e}")
            return None



    # --- Files ---
    def add_file(self, article_id, local_path, file_type='pdf', url=None):
        existing = self.session.query(File).filter_by(article_id=article_id, local_path=local_path).first()
        if not existing:
            new_file = File(
                article_id=article_id,
                local_path=local_path,
                file_type=file_type,
                url=url
            )
            self.session.add(new_file)
            self.session.commit()
            return new_file
        return existing

    def get_file_by_path(self, local_path):
        return self.session.query(File).filter_by(local_path=local_path).first()

    def record_analysis_log(self, file_id, method, status='completed'):
        """
        Record that a specific analysis method was run on a file.
        """
        log = FileAnalysisLog(
            file_id=file_id,
            method_name=method,
            status=status
        )
        self.session.add(log)
        self.session.commit()
    
    def is_method_already_run(self, file_id, method):
        """
        Check if a method has already been run successfully on a file.
        """
        log = self.session.query(FileAnalysisLog).filter_by(
            file_id=file_id, 
            method_name=method,
            status='completed'
        ).first()
        return log is not None
