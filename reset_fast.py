from sqlalchemy import create_engine, text
from database import DATABASE_URL

def reset_fast():
    print("Running fast SQL reset...")
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        # Check current counts
        result = conn.execute(text("SELECT COUNT(*) FROM articles WHERE status='completed'"))
        completed_before = result.scalar()
        print(f"Completed articles before: {completed_before}")
        
        # Reset those without emails
        # SQLite checking NOT IN might be slow on huge tables without index on article_id in captured_emails (which should be indexed)
        # But 200k rows is fine.
        
        sql = """
        UPDATE articles 
        SET status = 'downloaded', worker_id = NULL 
        WHERE status = 'completed' 
        AND id NOT IN (SELECT DISTINCT article_id FROM captured_emails)
        """
        
        result = conn.execute(text(sql))
        print(f"Reset {result.rowcount} articles to 'downloaded'.")
        conn.commit()
        
        # Check after
        result = conn.execute(text("SELECT COUNT(*) FROM articles WHERE status='downloaded'"))
        downloaded = result.scalar()
        print(f"Total downloaded (pending processing): {downloaded}")

if __name__ == "__main__":
    reset_fast()
