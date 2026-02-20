from database import get_session, Article, CapturedEmail, File
from sqlalchemy import not_, exists

def reset_articles_for_reprocessing():
    session = get_session()
    
    print("Identifying articles to re-process (Completed but no emails found)...")
    
    # Articles that are completed, have a file, but no captured emails
    # Subquery for articles with emails
    has_emails = session.query(CapturedEmail.article_id).distinct()
    
    articles_to_reset = session.query(Article).filter(
        Article.status == 'completed',
        Article.worker_id == None,
        ~Article.id.in_(has_emails) 
    ).all()
    
    print(f"Found {len(articles_to_reset)} articles that are 'completed' but have NO extracted emails.")
    
    # We should also check if they actually have a file
    count = 0
    for art in articles_to_reset:
        if art.files:
            art.status = 'downloaded'
            count += 1
            
        if count % 1000 == 0 and count > 0:
            print(f"Reset {count}...")
            session.commit()
            
    session.commit()
    print(f"Successfully reset {count} articles to 'downloaded' status.")
    print("Run './run_complete_cycle.sh' to re-process them with pdfplumber.")
    session.close()

if __name__ == "__main__":
    reset_articles_for_reprocessing()
