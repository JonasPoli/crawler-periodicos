import json
import os
from db_manager import DBManager

JOURNALS_FILE = 'journals.json'

def populate():
    if not os.path.exists(JOURNALS_FILE):
        print(f"Error: {JOURNALS_FILE} not found.")
        return

    print("Initializing Database...")
    db = DBManager()
    
    print(f"Reading {JOURNALS_FILE}...")
    with open(JOURNALS_FILE, 'r', encoding='utf-8') as f:
        journals_data = json.load(f)

    print(f"Found {len(journals_data)} journals. Importing...")
    
    count = 0
    imported_ids = []
    for j in journals_data:
        name = j.get('name')
        url = j.get('url')
        if not name or not url:
            print(f"Skipping invalid entry: {j}")
            continue
        
        # Determine source type
        source_type = j.get('type', 'ojs')
        
        # Create or Get
        journal = db.get_or_create_journal(
            name=name,
            url=url,
            source_type=source_type,
            acronym=j.get('acronym'), # Assuming these might exist or be added later
            issn=j.get('issn')
        )
        count += 1
        imported_ids.append(journal.id)
        print(f" Imported: {journal.name} ({journal.source_type})")

    print(f"Done. Imported/Verified {count} journals.")

    # Mede edições/artigos no site dos periódicos que ainda não têm medição (antes de processar)
    from journal_sizer import journals_needing_measurement, measure_journals, format_result
    to_measure = journals_needing_measurement(db.session, imported_ids)
    if to_measure:
        print(f"\nMeasuring size of {len(to_measure)} journal(s) on their sites...")
        measure_journals(to_measure, on_result=lambda spec, result: print(format_result(spec, result)))

if __name__ == "__main__":
    populate()
