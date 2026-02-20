import sqlite3
import time

def create_view():
    try:
        conn = sqlite3.connect('crawler.db', timeout=20) # 20s timeout
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("CREATE VIEW IF NOT EXISTS valid_emails AS SELECT email, domain_valid, mx_valid, smtp_valid FROM email_verifications WHERE final_status = 'valid';")
        conn.commit()
        conn.close()
        print("View 'valid_emails' created/verified.")
    except Exception as e:
        print(f"Error creating view: {e}")

if __name__ == "__main__":
    create_view()
