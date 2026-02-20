from db_manager import DBManager
from database import Edition, Article

db = DBManager()
session = db.session
try:
    pending_editions = session.query(Edition).filter(Edition.status == 'found').count()
    processing_editions = session.query(Edition).filter(Edition.status == 'processing').count()
    
    pending_crawling = session.query(Article).filter(Article.status == 'found').count()
    processing_crawling = session.query(Article).filter(Article.status == 'processing_crawling').count()
    downloaded_articles = session.query(Article).filter(Article.status == 'downloaded').count()
    
    pending_processing = session.query(Article).filter(Article.status == 'downloaded').count()
    processing_extract = session.query(Article).filter(Article.status == 'processing_extraction').count()
    completed = session.query(Article).filter(Article.status == 'completed').count()

    print(f"Editions - Found: {pending_editions}, Processing: {processing_editions}")
    print(f"Articles for Crawling - Found: {pending_crawling}, Processing: {processing_crawling}")
    print(f"Articles Downloaded: {downloaded_articles}")
    print(f"Articles for Processing - Pending: {pending_processing}, Processing: {processing_extract}")
    print(f"Completed Articles: {completed}")

finally:
    db.close()
