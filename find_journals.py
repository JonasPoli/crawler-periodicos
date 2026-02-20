import json
import re
from difflib import get_close_matches
import os

def clean_name(name):
    # Remove contents in parenthesis and special chars for better matching
    name = re.sub(r'\(.*?\)', '', name)
    name = name.replace('&', ' ')
    name = name.replace(':', ' ')
    name = name.replace('.', ' ')
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return name

def load_scielo_map():
    with open('scielo_scraped.json', 'r') as f:
        data = json.load(f)
    
    # Map cleaned title -> url
    # Also map exact title -> url
    mapping = {}
    for entry in data:
        mapping[clean_name(entry['title'])] = entry['url']
        mapping[entry['title'].lower()] = entry['url']
    return mapping, data

def main():
    scielo_map, raw_data = load_scielo_map()
    scielo_titles = list(scielo_map.keys())
    
    found_journals = []
    missing_journals = []
    
    # Read user list
    with open('user_list.txt', 'r') as f:
        lines = f.readlines()
        
    for line in lines:
        if not line.strip(): continue
        
        # Parse: ISSN TITLE QUALIS
        parts = line.strip().split()
        # Heuristic: Title is everything between ISSN (first) and Qualis (last)
        if parts[-1] in ['A2']:
            title_parts = parts[1:-1]
        else:
            title_parts = parts[1:]
            
        title_raw = " ".join(title_parts)
        cleaned_search = clean_name(title_raw)
        
        match_url = scielo_map.get(cleaned_search)
        
        # Fuzzy match if exact fails
        if not match_url:
            matches = get_close_matches(cleaned_search, scielo_titles, n=1, cutoff=0.85)
            if matches:
                match_url = scielo_map[matches[0]]
                # print(f"Fuzzy: '{title_raw}' -> '{matches[0]}' ({match_url})")

        if match_url:
            found_journals.append({
                "name": title_raw,
                "url": match_url,
                "type": "scielo"
            })
        else:
            missing_journals.append(title_raw)

    # Load existing to preserve OJS entries
    if os.path.exists('journals.json'):
         with open('journals.json', 'r') as f:
             existing = json.load(f)
    else:
         existing = []
         
    # Merge
    existing_urls = set(e['url'] for e in existing)
    added_count = 0
    
    for j in found_journals:
        if j['url'] not in existing_urls:
            existing.append(j)
            added_count += 1
            
    with open('journals.json', 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=4, ensure_ascii=False)
        
    print(f"Matched {len(found_journals)} SciELO journals.")
    print(f"Added {added_count} new entries to journals.json")
    print(f"Total journals in config: {len(existing)}")
    print(f"Still missing: {len(missing_journals)}")
    
    # Save missing
    with open('missing_journals.txt', 'w') as f:
        for m in missing_journals:
            f.write(m + '\n')

if __name__ == "__main__":
    main()
