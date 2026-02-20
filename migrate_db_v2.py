import sqlite3
import os

DB_FILE = "crawler.db"

def migrate():
    if not os.path.exists(DB_FILE):
        print("Database file not found.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    print("Creating captured_emails table...")
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS captured_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email VARCHAR(255) NOT NULL,
            article_id INTEGER NOT NULL,
            verification_status VARCHAR(50) DEFAULT 'PENDING',
            valid_syntax BOOLEAN,
            valid_domain BOOLEAN,
            valid_mx BOOLEAN,
            valid_smtp BOOLEAN,
            worker_id VARCHAR(50),
            lock_time DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(article_id) REFERENCES articles(id),
            UNIQUE(email, article_id)
        )
        """)
        print("Success.")
    except Exception as e:
        print(f"Error creating table: {e}")

    conn.commit()
    conn.close()
    print("Migration v2 completed.")

if __name__ == "__main__":
    migrate()
