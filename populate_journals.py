import json
import os

# Confirmed matches from research
new_entries = [
    {
        "name": "REVISTA DE EDUCACIÓN", 
        "url": "http://recyt.fecyt.es/index.php/Redu", 
        "type": "ojs"
    },
    {
        "name": "PERSPECTIVA (FLORIANÓPOLIS)", 
        "url": "https://periodicos.ufsc.br/index.php/perspectiva", 
        "type": "ojs"
    },
    {
        "name": "EDUCAÇÃO E FILOSOFIA", 
        "url": "https://periodicos.ufu.br/educacaoefilosofia", 
        "type": "ojs"
    },
    {
        "name": "PSICOLOGIA E SOCIEDADE", 
        "url": "https://www.scielo.br/j/psoc", 
        "type": "scielo"
    },
    {
        "name": "CONTEXTO & EDUCAÇÃO", 
        "url": "https://www.revistas.unijui.edu.br/index.php/contextoeducacao", 
        "type": "ojs"
    },
    {
        "name": "NOVA ECONOMIA", 
        "url": "https://www.scielo.br/j/neco", 
        "type": "scielo"
    },
    {
        "name": "REVISTA USP", 
        "url": "https://www.revistas.usp.br/revusp", 
        "type": "ojs"
    },
    {
        "name": "INFORMAÇÃO & SOCIEDADE: ESTUDOS", 
        "url": "https://periodicos.ufpb.br/index.php/ies", 
        "type": "ojs"
    },
    {
        "name": "ECONOMIA E SOCIEDADE", 
        "url": "https://www.scielo.br/j/ecos", 
        "type": "scielo"
    },
    {
        "name": "AMBIENTE & SOCIEDADE",
        "url": "https://www.scielo.br/j/asoc",
        "type": "scielo"
    }
]

file_path = 'journals.json'

if os.path.exists(file_path):
    with open(file_path, 'r') as f:
        existing = json.load(f)
else:
    existing = []

# Deduplicate
existing_urls = set(e['url'] for e in existing)
count = 0
for entry in new_entries:
    if entry['url'] not in existing_urls:
        existing.append(entry)
        count += 1

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(existing, f, indent=4, ensure_ascii=False)

print(f"Added {count} journals. Total: {len(existing)}")
