import json
import os

# Manual additions from recent research
manual_additions = [
    {
        "name": "LINHAS CRÍTICAS",
        "url": "http://seer.bce.unb.br/index.php/linhascriticas",
        "type": "ojs"
    },
    {
        "name": "REVISTA IBEROAMERICANA DE EDUCACIÓN",
        "url": "https://rieoei.org/RIE", 
        "type": "ojs" 
    },
    {
        "name": "EM ABERTO",
        "url": "https://emaberto.inep.gov.br/ojs3/index.php/emaberto",
        "type": "ojs"
    }
]

def clean_url(url):
    return url.rstrip('/')

def main():
    if os.path.exists('journals.json'):
         with open('journals.json', 'r') as f:
             data = json.load(f)
    else:
         data = []
         
    # Add manual additions
    data.extend(manual_additions)
    
    # Deduplicate by URL
    unique_journals = {}
    for entry in data:
        u = clean_url(entry['url'])
        # Prefer longer name if duplicate URL? Or first?
        if u not in unique_journals:
            unique_journals[u] = entry
        else:
            # If current entry name is UPPERCASE and existing is Title Case, keep Title Case?
            # actually usually Title Case is better.
            curr_name = entry['name']
            exist_name = unique_journals[u]['name']
            if curr_name.istitle() and not exist_name.istitle():
                 unique_journals[u] = entry
                 
    final_list = list(unique_journals.values())
    
    # Load missing list to add placeholders
    known_names = set(j['name'].upper() for j in final_list)
    
    with open('user_list.txt', 'r') as f:
        lines = f.readlines()
        
    placeholders = 0
    for line in lines:
        if not line.strip(): continue
        parts = line.strip().split()
        if parts[-1] in ['A2']: 
             title_parts = parts[1:-1]
        else:
             title_parts = parts[1:]
        name = " ".join(title_parts)
        
        # Check if matched (approximate)
        # We did fuzzy matching before, so if it's not in final_list, it's missing.
        # But we need a robust check.
        # Let's just add it if strictly not present, marking as TODO.
        
        # Simple check: is the name (upper) in known_names?
        # This misses fuzzy matches, but duplicates are better than missing.
        # Actually, let's look at the result of find_journals which produced 'missing_journals.txt'.
        pass 

    # Better: Read missing_journals.txt and add those.
    if os.path.exists('missing_journals.txt'):
        with open('missing_journals.txt', 'r') as f:
            for line in f:
                name = line.strip()
                if not name: continue
                
                # Check if we manually added it
                if any(m['name'].upper() == name.upper() for m in manual_additions):
                    continue
                    
                # Add placeholder
                final_list.append({
                    "name": name,
                    "url": "TODO_ENTER_URL_HERE",
                    "type": "ojs" # Assume OJS as default
                })
                placeholders += 1

    with open('journals.json', 'w', encoding='utf-8') as f:
        json.dump(final_list, f, indent=4, ensure_ascii=False)
        
    print(f"Final journals.json has {len(final_list)} entries.")
    print(f"Added {placeholders} placeholders for missing URLs.")

if __name__ == "__main__":
    main()
