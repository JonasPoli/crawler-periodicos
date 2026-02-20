from db_manager import DBManager
from database import Journal, Edition, Article

def verify():
    db = DBManager()
    
    print("--- Database Verification ---")
    
    # Check Journals
    journals = db.session.query(Journal).all()
    print(f"Journals count: {len(journals)}")
    if journals:
        print(f"Sample Journal: {journals[0]}")

    # Check Editions (Expect 0 initially)
    editions = db.session.query(Edition).all()
    print(f"Editions count: {len(editions)}")
    
    # Check Articles (Expect 0 initially)
    articles = db.session.query(Article).all()
    print(f"Articles count: {len(articles)}")

    if len(journals) > 0:
        print("\nSUCCESS: Database populated successfully.")
    else:
        print("\nWARNING: Database is empty. Did populate_db.py run?")

if __name__ == "__main__":
    verify()
