import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Boolean, UniqueConstraint, event
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.close()


# Define database file path
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DB_DIR, "crawler.db")
DATABASE_URL = f"sqlite:///{DB_FILE}"

Base = declarative_base()

class Journal(Base):
    __tablename__ = 'journals'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    url = Column(String(1024), nullable=False)
    acronym = Column(String(50), nullable=True)
    issn = Column(String(50), nullable=True)
    # Type: 'scielo' or 'ojs'
    source_type = Column(String(50), nullable=False, default='ojs')
    
    last_crawled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    active = Column(Boolean, default=True)
    # Status: 'active', 'completed', 'error'
    status = Column(String(50), default='active')

    # Relationships
    editions = relationship("Edition", back_populates="journal", cascade="all, delete-orphan")

    # New Metadata Fields
    address = Column(Text, nullable=True)
    publisher_name = Column(String(255), nullable=True)
    publisher_loc = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    issn_print = Column(String(50), nullable=True)
    issn_electronic = Column(String(50), nullable=True)
    qualis = Column(String(50), nullable=True)
    subject_area = Column(String(255), nullable=True)

    def __repr__(self):
        return f"<Journal(name={self.name}, url={self.url})>"

class Edition(Base):
    __tablename__ = 'editions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    journal_id = Column(Integer, ForeignKey('journals.id'), nullable=False)
    
    # Volume/Number info
    volume = Column(String(50), nullable=True)
    number = Column(String(50), nullable=True)
    year = Column(String(10), nullable=True)
    
    # Title often used in OJS issues (e.g. "Vol 1 No 2 (2020)")
    title = Column(String(255), nullable=True)
    url = Column(String(1024), nullable=False)
    
    # Status: 'found', 'processing', 'completed', 'error'
    status = Column(String(50), default='found')
    
    # Canonicalization and Alias support
    canonical_edition_id = Column(Integer, ForeignKey('editions.id', ondelete='SET NULL'), nullable=True)
    is_canonical = Column(Boolean, default=True, nullable=False)
    alias_notes = Column(String(500), nullable=True)

    # Locking for parallel processing
    worker_id = Column(String(50), nullable=True)
    lock_time = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Constraint to avoid duplicates
    __table_args__ = (UniqueConstraint('url', name='uq_edition_url'),)

    # Relationships
    journal = relationship("Journal", back_populates="editions")
    articles = relationship("Article", back_populates="edition", cascade="all, delete-orphan")
    canonical_edition = relationship("Edition", remote_side=[id], backref="aliases")

    def __repr__(self):
        return f"<Edition(journal_id={self.journal_id}, title={self.title})>"

class Article(Base):
    __tablename__ = 'articles'

    id = Column(Integer, primary_key=True, autoincrement=True)
    edition_id = Column(Integer, ForeignKey('editions.id'), nullable=False)
    
    title = Column(Text, nullable=False)
    url = Column(String(1024), nullable=True)
    doi = Column(String(255), nullable=True)
    abstract = Column(Text, nullable=True) # Resumo (PT usually)
    abstract_en = Column(Text, nullable=True) # Abstract (EN)
    
    # Metadata Fields
    publication_date = Column(DateTime, nullable=True) 
    submission_date = Column(DateTime, nullable=True)
    acceptance_date = Column(DateTime, nullable=True)
    page_numbers = Column(String(50), nullable=True)
    license_url = Column(String(255), nullable=True)
    copyright_holder = Column(String(255), nullable=True)
    language = Column(String(10), nullable=True)
    
    # Status: 'found', 'downloaded', 'parsed', 'metadata_enriched', 'error'
    status = Column(String(50), default='found')
    published_date = Column(String(50), nullable=True) # Textual date as scraped

    # Locking for parallel processing
    worker_id = Column(String(50), nullable=True)
    lock_time = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relationships
    edition = relationship("Edition", back_populates="articles")
    authors = relationship("Author", secondary="article_authors", back_populates="articles")
    keywords = relationship("Keyword", secondary="article_keywords", back_populates="articles")
    references = relationship("Reference", secondary="article_references", back_populates="articles")
    files = relationship("File", back_populates="article", cascade="all, delete-orphan")
    captured_emails = relationship("CapturedEmail", back_populates="article")

    def __repr__(self):
        return f"<Article(title={self.title[:30]}...)>"

class Author(Base):
    __tablename__ = 'authors'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    affiliation = Column(Text, nullable=True)
    orcid = Column(String(50), nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    articles = relationship("Article", secondary="article_authors", back_populates="authors")

    def __repr__(self):
        return f"<Author(name={self.name})>"

class ArticleAuthor(Base):
    __tablename__ = 'article_authors'

    article_id = Column(Integer, ForeignKey('articles.id'), primary_key=True)
    author_id = Column(Integer, ForeignKey('authors.id'), primary_key=True)

class Keyword(Base):
    __tablename__ = 'keywords'

    id = Column(Integer, primary_key=True, autoincrement=True)
    value = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    articles = relationship("Article", secondary="article_keywords", back_populates="keywords")

class Reference(Base):
    __tablename__ = 'references'

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False) 
    doi = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    articles = relationship("Article", secondary="article_references", back_populates="references")

class ArticleKeyword(Base):
    __tablename__ = 'article_keywords'

    article_id = Column(Integer, ForeignKey('articles.id'), primary_key=True)
    keyword_id = Column(Integer, ForeignKey('keywords.id'), primary_key=True)

class ArticleReference(Base):
    __tablename__ = 'article_references'

    article_id = Column(Integer, ForeignKey('articles.id'), primary_key=True)
    reference_id = Column(Integer, ForeignKey('references.id'), primary_key=True)

class File(Base):
    __tablename__ = 'files'

    id = Column(Integer, primary_key=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    
    # 'pdf', 'html', 'xml', etc.
    file_type = Column(String(20), nullable=False) 
    
    # Local path relative to project root or absolute
    local_path = Column(String(1024), nullable=True)
    
    # Remote URL
    url = Column(String(1024), nullable=True)
    
    checksum = Column(String(64), nullable=True) # SHA256 or similar
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    article = relationship("Article", back_populates="files")
    analysis_logs = relationship("FileAnalysisLog", back_populates="file", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<File(type={self.file_type}, path={self.local_path})>"


class FileAnalysisLog(Base):
    __tablename__ = 'file_analysis_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey('files.id'), nullable=False)
    
    # Method used: 'pypdf', 'pdfplumber', etc.
    method_name = Column(String(50), nullable=False)
    
    # Status: 'completed', 'failed', 'skipped'
    status = Column(String(50), default='completed')
    
    # Metadata or result summary could be added here if needed
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    file = relationship("File", back_populates="analysis_logs")

    def __repr__(self):
        return f"<FileAnalysisLog(file_id={self.file_id}, method={self.method_name})>"

class CapturedEmail(Base):
    __tablename__ = 'captured_emails'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False)
    article_id = Column(Integer, ForeignKey('articles.id'), nullable=False)
    
    # Verification Status
    verification_status = Column(String(50), default='PENDING') # PENDING, VALID, INVALID, UNKNOWN
    
    # Detailed Checks
    valid_syntax = Column(Boolean, nullable=True)
    valid_domain = Column(Boolean, nullable=True)
    valid_mx = Column(Boolean, nullable=True)
    valid_smtp = Column(Boolean, nullable=True)
    
    # Processing Metadata
    worker_id = Column(String(50), nullable=True)
    lock_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    article = relationship("Article")

    __table_args__ = (UniqueConstraint('email', 'article_id', name='uq_email_article'),)

    def __repr__(self):
        return f"<CapturedEmail(email={self.email}, status={self.verification_status})>"


class ExecutionRun(Base):
    __tablename__ = 'execution_runs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, index=True, nullable=False)
    mode = Column(String(50), default='super')
    journal_id = Column(Integer, nullable=True)
    status = Column(String(50), default='running') # 'running', 'completed', 'interrupted', 'crashed'
    workers_count = Column(Integer, default=2)
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    
    # Progress & Metrics
    editions_processed = Column(Integer, default=0)
    articles_crawled = Column(Integer, default=0)
    pdfs_downloaded = Column(Integer, default=0)
    pdfs_failed = Column(Integer, default=0)
    emails_extracted = Column(Integer, default=0)
    emails_valid = Column(Integer, default=0)
    emails_invalid = Column(Integer, default=0)
    
    # Speeds
    speed_articles_per_min = Column(String(50), default='0')
    speed_pdfs_per_min = Column(String(50), default='0')
    speed_emails_per_min = Column(String(50), default='0')
    
    # Crash / Recovery info
    crash_recovered_tasks = Column(Integer, default=0)
    system_info = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ExecutionRun(run_id={self.run_id}, status={self.status}, duration={self.duration_seconds}s)>"


class ErrorLog(Base):
    __tablename__ = 'error_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), index=True, nullable=True)
    phase = Column(String(50), nullable=False) # 'crawling', 'extraction', 'verification', 'system'
    journal_id = Column(Integer, nullable=True)
    article_id = Column(Integer, nullable=True)
    error_type = Column(String(100), nullable=False) # e.g. 'HTTPError', 'PDFExtractionError', 'SMTPTimeout', 'CrashRecovery'
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<ErrorLog(type={self.error_type}, phase={self.phase})>"


def init_db():
    engine = create_engine(DATABASE_URL, connect_args={'timeout': 60})
    Base.metadata.create_all(engine)
    
    # Auto-migration for SQLite columns
    try:
        with engine.connect() as conn:
            # Check existing columns in editions table
            result = conn.exec_driver_sql("PRAGMA table_info(editions)").fetchall()
            col_names = [r[1] for r in result]
            if 'canonical_edition_id' not in col_names:
                conn.exec_driver_sql("ALTER TABLE editions ADD COLUMN canonical_edition_id INTEGER REFERENCES editions(id) ON DELETE SET NULL")
            if 'is_canonical' not in col_names:
                conn.exec_driver_sql("ALTER TABLE editions ADD COLUMN is_canonical BOOLEAN DEFAULT 1")
            if 'alias_notes' not in col_names:
                conn.exec_driver_sql("ALTER TABLE editions ADD COLUMN alias_notes VARCHAR(500)")
            conn.commit()
    except Exception as e:
        pass
        
    return engine

def get_session(engine=None):
    if engine is None:
        engine = create_engine(DATABASE_URL, connect_args={'timeout': 60})
    Session = sessionmaker(bind=engine)
    return Session()
