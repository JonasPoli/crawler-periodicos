import requests
from bs4 import BeautifulSoup
from database import get_session, Article, Author, Keyword, Reference, ArticleAuthor, ArticleKeyword, ArticleReference, Journal
from sqlalchemy.exc import IntegrityError
import datetime
import re
import sys

# Regex for common delimiters
SPLIT_PATTERN = re.compile(r'[;,]\s*')

def parse_date(date_str):
    if not date_str: return None
    # Try common formats: '2023-10-01', '01/10/2023', 'Oct 1, 2023'
    # Simplified approach for OJS which usually uses YYYY-MM-DD or localised
    try:
        if '-' in date_str:
            return datetime.datetime.strptime(date_str.strip(), '%Y-%m-%d')
        elif '/' in date_str:
            # Assume DD/MM/YYYY for Brazil
            return datetime.datetime.strptime(date_str.strip(), '%d/%m/%Y')
    except:
        pass
    return None

def detect_language(text):
    if not text: return 'unknown'
    text = text.lower()
    # Simple stop word counters
    en_words = {'the', 'and', 'of', 'to', 'in', 'is', 'that', 'for', 'it', 'with', 'as', 'are', 'on', 'by', 'this', 'we', 'study'}
    pt_words = {'o', 'a', 'e', 'de', 'do', 'da', 'que', 'em', 'para', 'com', 'na', 'no', 'um', 'uma', 'os', 'as', 'por', 'esse', 'este'}
    
    tokens = re.findall(r'\b\w+\b', text)
    en_count = sum(1 for t in tokens if t in en_words)
    pt_count = sum(1 for t in tokens if t in pt_words)
    
    if en_count > pt_count:
        return 'en'
    elif pt_count > en_count:
        return 'pt'
    return 'unknown'

def get_or_create(session, model, **kwargs):
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance
    else:
        instance = model(**kwargs)
        session.add(instance)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            instance = session.query(model).filter_by(**kwargs).first()
        return instance

def clean_text(text):
    if not text:
        return None
    return " ".join(text.split())

def parse_authors_html(soup):
    authors_data = []
    # Try the section structure provided by user
    section = soup.find('section', class_='item authors')
    if section:
        for li in section.find_all('li'):
            name = li.find('span', class_='name')
            name_text = clean_text(name.get_text()) if name else None
            
            orcid = None
            orcid_span = li.find('span', class_='orcid')
            if orcid_span:
                a_tag = orcid_span.find('a')
                if a_tag:
                    orcid = clean_text(a_tag.get('href'))
            
            if name_text:
                authors_data.append({'name': name_text, 'orcid': orcid})
    return authors_data

def parse_keywords_html(soup):
    keywords = []
    section = soup.find('section', class_='item keywords')
    if section:
        val_span = section.find('span', class_='value')
        if val_span:
            text = clean_text(val_span.get_text())
            if text:
                # Split by newline, comma or semicolon
                parts = re.split(r'[;,\n]', text)
                keywords = [clean_text(p) for p in parts if clean_text(p)]
    
    # Fallback: check for p strong keywords
    if not keywords:
        for p in soup.find_all('p'):
            if 'Palavras-chave:' in p.get_text():
                text = p.get_text().replace('Palavras-chave:', '')
                parts = re.split(r'[;,\n]', text)
                keywords = [clean_text(p) for p in parts if clean_text(p)]
                break
    return keywords

def parse_abstract_html(soup):
    section = soup.find('section', class_='item abstract')
    if section:
        # Get all paragraphs
        ps = section.find_all('p')
        text = "\n".join([clean_text(p.get_text()) for p in ps])
        if text:
            return text
    return None

def parse_references_html(soup):
    refs = []
    section = soup.find('section', class_='item references')
    if section:
        val_div = section.find('div', class_='value')
        if val_div:
            for p in val_div.find_all('p'):
                text = clean_text(p.get_text())
                if text:
                    doi = None
                    # Try to extract DOI from link text or href
                    link = p.find('a')
                    if link and 'doi.org' in (link.get('href') or ''):
                        doi = link.get('href')
                    
                    refs.append({'text': text, 'doi': doi})
    return refs

def enrich_article(session, article):
    print(f"Enriching Article {article.id}: {article.title[:50]}...")
    
    if not article.url:
        print("  No URL, skipping.")
        return

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(article.url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"  Failed to fetch {article.url} (Status {response.status_code})")
            return
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # --- 1. Basic Metadata from Metatags ---
        meta_doi = soup.find('meta', attrs={'name': 'citation_doi'})
        if meta_doi:
            article.doi = meta_doi.get('content')
            
        meta_date = soup.find('meta', attrs={'name': 'citation_date'})
        if meta_date:
            article.published_date = meta_date.get('content')
            # Try parsing date
            try:
                article.publication_date = datetime.datetime.strptime(article.published_date, '%Y/%m/%d')
            except:
                pass

        # --- 2. Abstract & Resumo ---
        # OJS often has multiple citation_abstract with xml:lang
        # Or <div class="item abstract">
        
        # Reset defaults
        article.abstract = None
        article.abstract_en = None
        
        # 1. Try Meta Tags
        meta_abstracts = soup.find_all('meta', attrs={'name': 'citation_abstract'})
        if not meta_abstracts:
             # Try DC.Description
             meta_abstracts = soup.find_all('meta', attrs={'name': 'DC.Description'})

        for ma in meta_abstracts:
            content = clean_text(ma.get('content'))
            if not content: continue
            
            lang = ma.get('xml:lang', '').lower()
            
            # If explicit lang is missing, detect it
            if not lang:
                detected = detect_language(content)
                if detected != 'unknown':
                    lang = detected
            
            if 'en' in lang:
                if not article.abstract_en or len(content) > len(article.abstract_en):
                    article.abstract_en = content
            elif 'pt' in lang or 'es' in lang: # Group PT/ES as main Abstract for now, or detect strict PT
                if not article.abstract or len(content) > len(article.abstract):
                    article.abstract = content
            else:
                # Fallback: if we have nothing, store in abstract (PT slot)
                if not article.abstract:
                    article.abstract = content

        # 2. Structure Fallback (only if missing)
        if not article.abstract_en:
             # Look for specific English abstract sections
             # <div id="article-abstract-en"> or <h3>Abstract</h3>
             # Heuristic: headers
             for h in soup.find_all(['h1', 'h2', 'h3', 'h4']):
                 if 'abstract' in h.get_text().lower():
                     # content might be next sibling or parent's sibling
                     # Simplified: find the parent div
                     parent = h.find_parent('div')
                     if parent:
                         txt = clean_text(parent.get_text())
                         # subtract header
                         txt = txt.replace(clean_text(h.get_text()), '').strip()
                         # Verify it's English
                         if detect_language(txt) == 'en':
                             article.abstract_en = txt
                             break

        # --- 2.1 Dates (HTML scraping) ---

        # --- 2.1 Dates (HTML scraping) ---
        # Submitted
        div_submitted = soup.find('div', class_='item date_submitted')
        if div_submitted:
            val = div_submitted.find('div', class_='value')
            if val:
                text = clean_text(val.get_text())
                if text:
                    article.submission_date = parse_date(text)

        # Published
        div_published = soup.find('div', class_='item date_published')
        if div_published:
            val = div_published.find('div', class_='value')
            if val:
                text = clean_text(val.get_text())
                if text:
                    article.publication_date = parse_date(text)
        
        # Accepted
        div_accepted = soup.find('div', class_='item date_accepted')
        if div_accepted:
             val = div_accepted.find('div', class_='value')
             if val:
                 text = clean_text(val.get_text())
                 if text:
                     article.acceptance_date = parse_date(text)

        # Pages
        # Try meta citation_firstpage/lastpage
        start_page = soup.find('meta', attrs={'name': 'citation_firstpage'})
        end_page = soup.find('meta', attrs={'name': 'citation_lastpage'})
        if start_page and end_page:
            article.page_numbers = f"{start_page.get('content')}-{end_page.get('content')}"
        
        # --- 2.2 License & Copyright ---
        license_link = soup.find('a', rel='license')
        if license_link:
            article.license_url = license_link.get('href')
        
        copy_text = soup.find(string=re.compile(r'Copyright|©', re.IGNORECASE))
        if copy_text:
            article.copyright_holder = clean_text(copy_text)[:255]
            
        # --- 2.3 Journal Metadata (Update Journal Record) ---
        # Only update if fields are empty to avoid overwriting with partial data constantly
        journal = article.edition.journal
        if journal:
            # ISSNs
            if not journal.issn_print:
                issn_p = soup.find(string=re.compile(r'ISSN.*Impresso|Print.*ISSN', re.IGNORECASE))
                if issn_p:
                    # Extract ISSN pattern XXXX-XXXX
                    m = re.search(r'\d{4}-\d{4}', issn_p)
                    if m: journal.issn_print = m.group(0)
            
            if not journal.issn_electronic:
                issn_e = soup.find(string=re.compile(r'ISSN.*Eletrônico|Electronic.*ISSN', re.IGNORECASE))
                if issn_e:
                    m = re.search(r'\d{4}-\d{4}', issn_e)
                    if m: journal.issn_electronic = m.group(0)

            # Contact Info (Heuristic: usually in footer)
            footer = soup.find('footer') or soup.find('div', id='sidebar')
            if footer:
                f_text = footer.get_text()
                
                # Email
                if not journal.email:
                    emails = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', f_text)
                    if emails:
                        journal.email = emails[0][:255]
                        
                # Phone (Simple pattern)
                if not journal.phone:
                    phones = re.findall(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}', f_text)
                    if phones:
                        journal.phone = phones[0][:50]
                        
                # Address (Hard without NLP, try looking for patterns or "Endereço")
                if not journal.address:
                    if "Endereço" in f_text or "Address" in f_text:
                        # Extract a chunk around it? Too risky for noise. 
                        # Let's just save the footer snippet if it's short? No.
                        # Leave address for manual or more specific scrapers.
                        pass

        # --- 3. Authors ---
        authors_extracted = parse_authors_html(soup)
        if not authors_extracted:
            # Fallback to meta tags
            meta_authors = soup.find_all('meta', attrs={'name': 'citation_author'})
            for ma in meta_authors:
                authors_extracted.append({'name': ma.get('content'), 'orcid': None})
        
        # Save Authors
        for auth_data in authors_extracted:
            # Check if author exists by ORCID (if present) or Name
            author = None
            if auth_data['orcid']:
                author = session.query(Author).filter_by(orcid=auth_data['orcid']).first()
            
            if not author:
                 author = session.query(Author).filter_by(name=auth_data['name']).first()
            
            if not author:
                author = Author(name=auth_data['name'], orcid=auth_data['orcid'])
                session.add(author)
                session.commit()
            else:
                # Update ORCID if missing
                if not author.orcid and auth_data['orcid']:
                    author.orcid = auth_data['orcid']
                    session.commit()
            
            # Link to article
            if author not in article.authors:
                article.authors.append(author)

        # --- 4. Keywords ---
        keywords_extracted = parse_keywords_html(soup)
        for kw_text in keywords_extracted:
            kw_obj = get_or_create(session, Keyword, value=kw_text)
            if kw_obj not in article.keywords:
                article.keywords.append(kw_obj)

        # --- 5. References ---
        refs_extracted = parse_references_html(soup)
        for ref_data in refs_extracted:
            # Check if ref exists by text (exact match)
            # This might be tricky with minor whitespace diffs, but we cleaned text
            ref_obj = session.query(Reference).filter(Reference.text == ref_data['text']).first()
            if not ref_obj:
                ref_obj = Reference(text=ref_data['text'], doi=ref_data['doi'])
                session.add(ref_obj)
                session.commit()
            
            if ref_obj not in article.references:
                article.references.append(ref_obj)

        # Mark as enriched
        article.status = 'metadata_enriched'
        session.commit()
        print("  Enrichment completed.")

    except Exception as e:
        print(f"  Error processing {article.id}: {e}")
        session.rollback()

def main():
    session = get_session()
    
    # To force re-check of everything (as user mostly likely wants to backfill missing fields),
    # we can iterate over all articles. But to avoid infinite loops if it fails, maybe check if metadata is missing?
    # For now, let's process those that are NOT 'metadata_full' (a new status we could use, or just reuse 'metadata_enriched' but we already used it).
    # Since we added new fields, we should re-process 'metadata_enriched' ones too if we want to fill the new fields.
    # Let's iterate all valid articles.
    
    # Process batch of 50 at a time to keep memory low
    offset = 0
    while True:
        articles = session.query(Article).filter(Article.url.isnot(None))\
                          .order_by(Article.id).limit(50).offset(offset).all()
        
        if not articles:
            break
            
        print(f"Processing batch from {offset}...")
        for article in articles:
            enrich_article(session, article)
        
        offset += 50

if __name__ == "__main__":
    main()
