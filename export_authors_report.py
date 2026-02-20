import sqlite3
import csv
import os

DB_PATH = 'crawler.db'
SQL_FILE = 'query_authors_full.sql'
OUTPUT_CSV = 'authors_full_report.csv'

def export_data():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database '{DB_PATH}' not found.")
        return

    if not os.path.exists(SQL_FILE):
        print(f"Error: SQL file '{SQL_FILE}' not found.")
        return

    print(f"Connecting to database '{DB_PATH}'...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    with open(SQL_FILE, 'r') as f:
        query = f.read()

    print("Executing query...")
    try:
        cursor.execute(query)
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        conn.close()
        return

    # Get column names from cursor description
    column_names = [description[0] for description in cursor.description]

    rows = cursor.fetchall()
    print(f"Fetched {len(rows)} rows.")

    print(f"Writing to '{OUTPUT_CSV}'...")
    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(column_names)
        writer.writerows(rows)

    conn.close()
    print("Done.")

if __name__ == "__main__":
    export_data()
