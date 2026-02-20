
import json
import requests
from bs4 import BeautifulSoup
import re
import os

JOURNALS_FILE = 'journals.json'

USER_URLS = [
    "https://ojs.revistadcs.com/index.php/revista/index?_gl=1*15ruthe*_gcl_aw*R0NMLjE3NzAyNDgzNTIuQ2owS0NRaUEtWXZNQmhEdEFSSXNBSFp1VXpJUy0xN1E5cV9IZVN1NkFVLWxTVWR3MzJBdmN5NGwzQUVOSHVKTFVSOW9jWHZ3eFExRzJRTWFBamFMRUFMd193Y0I.*_gcl_au*MjA4MDgzNjE1My4xNzY4ODU1ODk3",
    "https://ojs.cuadernoseducacion.com/ojs/index.php/ced",
    "https://v3.cadernoscajuina.pro.br/index.php/revista",
    "https://ojs.revistacontemporanea.com/ojs/index.php/home",
    "https://ojs.revistagesec.org.br/secretariado/issue/view/80",
    "https://revista.ioles.com.br/boca/index.php/revista",
    "https://remunom.ojsbr.com/multidisciplinar",
    "https://www.artefactumjournal.com/index.php/artefactum",
    "https://periodicos.newsciencepubl.com/arace",
    "https://ojs.observatoriolatinoamericano.com/ojs/index.php/olel",
    "https://rgsa.openaccesspublications.org/rgsa/issue/archive",
    "https://ojs.revistacontribuciones.com/ojs/index.php/clcs",
    "https://ojs.revistadelos.com/ojs/index.php/delos"
]

HTML_SNIPPET = """
<div class="owl-stage" style="transform: translate3d(-5550px, 0px, 0px); transition: 0.25s; width: 19980px;"><div class="owl-item cloned" style="width: 185px;"><a href="https://ojs.jaff.org.br/ojs/index.php/jaff" target="_blank">
          	<img title="JAFF - Jornal de Assistência Farmacêutica e Farmacoeconomia" src="assets/img/clients/client-39.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://futurepublishersgroup.com/" target="_blank">
          	<img title="Future Publishers Group" src="assets/img/clients/client-40.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://periodicos.unesc.net/ojs/index.php/" target="_blank">
          	<img title="Periódicos UNESC" src="assets/img/clients/client-41.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://europubpublications.com/ojs/index.php/ejhr/about" target="_blank">
          	<img title="Europub Journal of Health Research" src="assets/img/clients/client-32.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BASR" target="_blank">
          	<img title="Brazilian Applied Science Review" src="assets/img/clients/client-17.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://revista.sabnet.org/ojs/index.php/sab" target="_blank">
          	<img title="Sociedade de Arqueologia Brasileira" src="assets/img/clients/client-42.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://revistafundacao.fsa.br/ojs/index.php/rfa" target="_blank">
          	<img title="Centro Universitário Fundação Santo André" src="assets/img/clients/client-43.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://faculdadedeamericana.com.br/ojs/" target="_blank">
          	<img title="FAM - Faculdade de Americana" src="assets/img/clients/client-44.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/sees" target="_blank">
          	<img title="Studies in Engineering amd Exact Sciences" src="assets/img/clients/client-26.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://revistacontemporanea.com/ojs/index.php/home" target="_blank">
          	<img title="Revista Contemporânea" src="assets/img/clients/client-45.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://southfloridapublishing.com/ojs/index.php/sfjeas" target="_blank">
          	<img title="South Florida Journal of Environmental and Animal Science" src="assets/img/clients/client-6.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://campodahistoria.com.br/ojs/index.php/rcdh" target="_blank">
          	<img title="Revista Campo da História" src="assets/img/clients/client-46.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://focopublicacoes.com.br/" target="_blank">
          	<img title="Revista Foco Publicações" src="assets/img/clients/client-47.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://cientifica.azeiteseolivais.com.br/ojs/index.php/rao" target="_blank">
          	<img title="Revista Azeites &amp; Olivais" src="assets/img/clients/client-48.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/sssr" target="_blank">
          	<img title="Studies in Social Sciences Review" src="assets/img/clients/client-21.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://reflexaoacademica.com.br/" target="_blank">
          	<img title="Editora Reflexão Acadêmica" src="assets/img/clients/client-49.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BJAER" target="_blank">
          	<img title="Brazilian Journal of Animal and Environmental Research" src="assets/img/clients/client-15.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://revistagc.com.br/ojs/index.php/rgc" target="_blank">
          	<img title="Revista Gestão e Conhecimento" src="assets/img/clients/client-50.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://openaccesspublications.org/" target="_blank">
          	<img title="Open Access Publications" src="assets/img/clients/client-51.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://europubpublications.com/ojs/index.php/ejssr" target="_blank">
          	<img title="Europub Journal of Social Sciences Research" src="assets/img/clients/client-33.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://mr-society.com/" target="_blank">
          	<img title="Management Research Society" src="assets/img/clients/client-52.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://mr-society.com/ojs/index.php/jma" target="_blank">
          	<img title="International Journal of Management Affairs" src="assets/img/clients/client-53.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://latinamericanpublicacoes.com.br/ojs/index.php/jdev" target="_blank">
          	<img title="Latin American Journal of Development" src="assets/img/clients/client-13.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/smr" target="_blank">
          	<img title="Studies in Multidisciplinary Reviews" src="assets/img/clients/client-27.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://southfloridapublishing.com/ojs/index.php/jdev" target="_blank">
          	<img title="South Florida Journal of Development" src="assets/img/clients/client-7.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://mr-society.com/ojs/index.php/jhra" target="_blank">
          	<img title="Journal of Medical Affairs" src="assets/img/clients/client-54.png" alt="">
          </a></div><div class="owl-item cloned" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BJHR" target="_blank">
          	<img title="Brazilian Journal of Health Review" src="assets/img/clients/client-16.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://malque.pub/ojs/index.php/msj" target="_blank">
          	<img title="Multidisciplinary Science Journal" src="assets/img/clients/client-1.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BJT" target="_blank">
          	<img title="Brazilian Journal of Technology" src="assets/img/clients/client-14.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://latinamericanpublicacoes.com.br/" target="_blank">
          	<img title="Latin American Publicações" src="assets/img/clients/client-11.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/ses" target="_blank">
          	<img title="Studies in Education Sciences" src="assets/img/clients/client-23.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://southfloridapublishing.com/ojs/index.php/jhea" target="_blank">
           	<img title="South Florida Journal of Health" src="assets/img/clients/client-2.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://europubpublications.com/ojs/index.php/ejaer" target="_blank">
          	<img title="Europub Journal of Animal and Environmental Research" src="assets/img/clients/client-29.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://jics.org.br/ojs/index.php/JICS" target="_blank">
          	<img title="JICS - Sociedade Brasileira de Computação" src="assets/img/clients/client-37.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://malque.pub/ojs/index.php/avr" target="_blank">
          	<img title="Applied Veterinary Research" src="assets/img/clients/client-3.png" alt="">
          </a></div><div class="owl-item active" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BJB" target="_blank">
          	<img title="Brazilian Journal of Business" src="assets/img/clients/client-18.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://europubpublications.com/ojs/index.php/ejeer" target="_blank">
          	<img title="Europub Journal of Exact and Engineering Research" src="assets/img/clients/client-30.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://malque.pub/ojs/index.php/jabb" target="_blank">
          	<img title="Journal of Animal Behaviour and Biometeorology" src="assets/img/clients/client-8.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://malque.pub/ojs/" target="_blank">
          	<img title="MALQUE Publishing" src="assets/img/clients/client-9.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://malque.pub/ojs/index.php/raaf" target="_blank">
          	<img title="Research in Alternative Animal Feeds" src="assets/img/clients/client-10.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/shs" target="_blank">
          	<img title="Studies in Health Sciences" src="assets/img/clients/client-24.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://europubpublications.com/ojs/index.php/ejer" target="_blank">
          	<img title="Europub Journal of Education Research" src="assets/img/clients/client-31.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://studiespublicacoes.com.br/ojs/index.php/seas" target="_blank">
          	<img title="Studies in Environmental and Animal Sciences" src="assets/img/clients/client-25.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://brazilianjournals.com/ojs/index.php/BRJD" target="_blank">
          	<img title="Brazilian Journal of Development" src="assets/img/clients/client-19.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://southfloridapublishing.com/" target="_blank">
          	<img title="South Florida Publishing" src="assets/img/clients/client-5.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://latinamericanpublicacoes.com.br/ojs/index.php/ah" target="_blank">
          	<img title="Journal of Archives of Health" src="assets/img/clients/client-12.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://studiespublicacoes.com.br/" target="_blank">
          	<img title="Studies Publicações" src="assets/img/clients/client-20.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://acessoacademico.com.br/" target="_blank">
          	<img title="Acesso Acadêmico" src="assets/img/clients/client-22.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://malque.pub/ojs/index.php/mr" target="_blank">
          	<img title="Multidisciplinary Reviews" src="assets/img/clients/client-4.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://europubpublications.com/" target="_blank">
          	<img title="EUROPUB - European Publications" src="assets/img/clients/client-28.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://www.brazilianjournals.com.br/" target="_blank">
          	<img title="Brazilian Journals Publicações de Periódicos e Editora Ltda." src="assets/img/clients/client-34.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://revista.provitima.org/ojs/index.php/rpv" target="_blank">
          	<img title="Revista Internacional de Vitimologia e Justiça Restaurativa" src="assets/img/clients/client-35.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://jics.org.br/ojs/index.php/JICS" target="_blank">
          	<img title="JICS - Sociedade Brasileira de Microeletrônica" src="assets/img/clients/client-36.png" alt="">
          </a></div><div class="owl-item" style="width: 185px;"><a href="https://editorainovar.com.br/" target="_blank">
          	<img title="Editora INOVAR" src="assets/img/clients/client-38.png" alt="">
          </a></div>
"""

def clean_url(url):
    """Normalize OJS/SciELO URLs."""
    url = url.strip()
    # Remove query parameters that might break matching or be session specific
    if '?' in url:
        url = url.split('?')[0]
    # Remove trailing slash
    if url.endswith('/'):
        url = url[:-1]
    
    # Specific fix for OJS: remove /index.php/journalname/index if present
    # to get base url, or keep it if that's what we want?
    # Usually orchestrator expects base URL. 
    # For OJS, base URL is often .../index.php/journalname
    
    return url

def guess_name(url):
    """Guess journal name from URL."""
    try:
        if 'scielo.br/j/' in url:
            return url.split('scielo.br/j/')[1].upper()
        
        # OJS common patterns
        if '/index.php/' in url:
             name_part = url.split('/index.php/')[1]
             if '/' in name_part:
                 name_part = name_part.split('/')[0]
             return name_part.replace('-', ' ').title()
             
        # Generic
        parts = url.split('/')
        return parts[-1].replace('-', ' ').title()
    except:
        return "Unknown Journal"

def guess_type(url):
    if 'scielo' in url:
        return 'scielo'
    return 'ojs'

def extract_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        # Filter logic: Must be likely a journal link
        if 'ojs' in href or 'scielo' in href or '/index.php' in href:
             # Try to find a title from img alt or text
             title = a.get_text(strip=True)
             if not title:
                 img = a.find('img')
                 if img and img.get('title'):
                     title = img.get('title')
                 elif img and img.get('alt'):
                     title = img.get('alt')
             
             if not title:
                 title = guess_name(href)
                 
             links.append({'url': clean_url(href), 'name': title, 'type': guess_type(href)})
    return links

def fetch_scielo_journals():
    """Fetch list of journals from SciELO alphabetical list."""
    print("Fetching more journals from SciELO (timeout 30s)...")
    # SciELO Alphabetic List
    url = "https://www.scielo.br/p/journals/list/alpha"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch SciELO list: {response.status_code}")
            return []
            
        soup = BeautifulSoup(response.content, 'html.parser')
        
        scielo_links = []
        # In the new SciELO interface, journals are often in a table or list
        # Look for links that contain /j/ and are not the base url
        
        # Try specifically the table lines if possible, or just all links
        for a in soup.find_all('a', href=True):
            href = a['href']
            # Pattern: https://www.scielo.br/j/acronym/
            if '/j/' in href:
                # normalize
                if href.startswith('/'):
                    href = f"https://www.scielo.br{href}"
                
                # Check if it looks like a journal home
                # e.g. https://www.scielo.br/j/agrob/
                if href.count('/') >= 5: 
                     name = a.get_text(strip=True)
                     if not name: 
                         name = guess_name(href)
                     
                     if name and len(name) > 2:
                        scielo_links.append({'url': href, 'name': name, 'type': 'scielo'})
        
        # Deduplicate by URL
        unique_links = {}
        for l in scielo_links:
            u = clean_url(l['url'])
            if u not in unique_links:
                unique_links[u] = l
        
        print(f"Found {len(unique_links)} journals from SciELO.")
        return list(unique_links.values())
        
    except Exception as e:
        print(f"Error fetching SciELO: {e}")
        return []

def main():
    # 1. Load existing
    if os.path.exists(JOURNALS_FILE):
        with open(JOURNALS_FILE, 'r') as f:
            journals = json.load(f)
    else:
        journals = []
    
    print(f"Initial journal count: {len(journals)}")
    
    existing_urls = set(j['url'] for j in journals)
    
    # 2. Add User URLs
    print("Processing User URLs...")
    for url in USER_URLS:
        clean = clean_url(url)
        if clean not in existing_urls:
            journals.append({
                "name": guess_name(clean),
                "url": clean,
                "type": guess_type(clean)
            })
            existing_urls.add(clean)
            print(f"Added: {clean}")

    # 3. Add HTML Snippet URLs
    print("\nProcessing HTML Snippet...")
    html_entries = extract_from_html(HTML_SNIPPET)
    for entry in html_entries:
        if entry['url'] not in existing_urls:
            journals.append({
                "name": entry['name'],
                "url": entry['url'],
                "type": entry['type']
            })
            existing_urls.add(entry['url'])
            print(f"Added: {entry['url']} ({entry['name']})")

    # 4. Check Count & Fetch from SciELO if needed
    # Filter only valid journals for the count check
    valid_journals = [j for j in journals if 'TODO_ENTER_URL' not in j['url']]
    current_count = len(valid_journals)
    print(f"\nCurrent valid count: {current_count}")
    
    if current_count < 100:
        needed = 100 - current_count
        print(f"Need {needed} more journals. Fetching from SciELO...")
        scielo_entries = fetch_scielo_journals()
        
        added_count = 0
        for entry in scielo_entries:
            if entry['url'] not in existing_urls:
                journals.append(entry)
                existing_urls.add(entry['url'])
                added_count += 1
                if current_count + added_count >= 100:
                    break
        print(f"Added {added_count} journals from SciELO.")
    
    # Fallback if still under 100
    current_count = len(journals)
    if current_count < 100:
        print(f"Still need {100 - current_count} journals. Using manual fallback list...")
        fallback_urls = [
            "https://www.scielo.br/j/rsp", "https://www.scielo.br/j/pope", "https://www.scielo.br/j/ress", 
            "https://www.scielo.br/j/csc", "https://www.scielo.br/j/physis", "https://www.scielo.br/j/icse",
            "https://www.scielo.br/j/rbepid", "https://www.scielo.br/j/cadsc", "https://www.scielo.br/j/reben",
            "https://www.scielo.br/j/reeusp", "https://www.scielo.br/j/tce", "https://www.scielo.br/j/rlae",
            "https://www.scielo.br/j/ape", "https://www.scielo.br/j/ean", "https://www.scielo.br/j/reme",
            "https://www.scielo.br/j/ref", "https://www.scielo.br/j/rgenf", "https://www.scielo.br/j/ree",
            "https://www.scielo.br/j/coggit", "https://www.scielo.br/j/rbfar", "https://www.scielo.br/j/jbchs",
            "https://www.scielo.br/j/qn", "https://www.scielo.br/j/jbcs", "https://www.scielo.br/j/po",
            "https://www.scielo.br/j/gp", "https://www.scielo.br/j/prod", "https://www.scielo.br/j/asoc",
            "https://www.scielo.br/j/rbe", "https://www.scielo.br/j/rbme", "https://www.scielo.br/j/motriz"
        ]
        
        for url in fallback_urls:
            cleaned = clean_url(url)
            if cleaned not in existing_urls:
                journals.append({
                    "name": guess_name(cleaned),
                    "url": cleaned,
                    "type": guess_type(cleaned)
                })
                existing_urls.add(cleaned)
                if len(journals) >= 105: # Go a bit over to be safe
                    break


    # 5. Save
    # Filter out TODOs if we want to clean up
    journals = [j for j in journals if 'TODO_ENTER_URL' not in j['url']]
    
    with open(JOURNALS_FILE, 'w') as f:
        json.dump(journals, f, indent=4, ensure_ascii=False)
    
    print(f"\nFinal journal count: {len(journals)}")
    print(f"Updated {JOURNALS_FILE}")

if __name__ == "__main__":
    main()
