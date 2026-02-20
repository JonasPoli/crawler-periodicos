import sqlite3

DB_FILE = "crawler.db"

def migrate():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # helper to check col
    def col_exists(table, col):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [info[1] for info in cursor.fetchall()]
        return col in cols

    def add_col(table, col, type_def):
        if not col_exists(table, col):
            print(f"Adding {col} to {table}...")
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {type_def}")
            except Exception as e:
                print(f"Error adding {col}: {e}")
        else:
            print(f"Column {col} already exists in {table}.")

    # Articles
    # abstract already exists
    add_col('articles', 'abstract_en', 'TEXT')
    add_col('articles', 'publication_date', 'DATETIME')
    add_col('articles', 'submission_date', 'DATETIME')
    add_col('articles', 'acceptance_date', 'DATETIME')
    add_col('articles', 'page_numbers', 'VARCHAR(50)')
    add_col('articles', 'license_url', 'VARCHAR(255)')
    add_col('articles', 'copyright_holder', 'VARCHAR(255)')
    add_col('articles', 'language', 'VARCHAR(10)')

    # Journals
    add_col('journals', 'address', 'TEXT')
    add_col('journals', 'publisher_name', 'VARCHAR(255)')
    add_col('journals', 'publisher_loc', 'VARCHAR(255)')
    add_col('journals', 'email', 'VARCHAR(255)')
    add_col('journals', 'phone', 'VARCHAR(50)')
    add_col('journals', 'issn_print', 'VARCHAR(50)')
    add_col('journals', 'issn_electronic', 'VARCHAR(50)')
    add_col('journals', 'qualis', 'VARCHAR(50)')
    add_col('journals', 'subject_area', 'VARCHAR(255)')

    # Authors
    add_col('authors', 'orcid', 'VARCHAR(50)')

    conn.commit()
    conn.close()
    print("Migration finished.")

if __name__ == "__main__":
    migrate()
