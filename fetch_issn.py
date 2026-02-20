#!/usr/bin/env python3
"""
fetch_issn.py - Scrapes ISSN (Print and Electronic) from journal URLs.

Scans all journals in the database that are missing issn_print or issn_electronic
and attempts to extract them from the journal's homepage and /about page.

Strategies (in order):
  1. Meta tags: citation_issn, DC.Identifier (ISSN)
  2. SciELO pattern: "Versão impressa ISSN:" / "Versão on-line ISSN:"
  3. Free text patterns: "ISSN print", "eISSN", "ISSN Impresso", "ISSN Eletrônico/Online"
  4. Fallback: extract all ISSN-like patterns (XXXX-XXXX) from the page
  5. Repeat strategies on /about page if main page didn't yield results
"""

import requests
from bs4 import BeautifulSoup
from database import get_session, Journal
import re
import time
import sys

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
ISSN_RE = re.compile(r'\b(\d{4}-\d{3}[\dXx])\b')
TIMEOUT = 15


def extract_issn_from_soup(soup):
    """Extract ISSN print and electronic from a BeautifulSoup object."""
    issn_print = None
    issn_electronic = None
    
    # --- Strategy 1: Meta tags ---
    # Some OJS sites use citation_issn
    meta_issn = soup.find('meta', attrs={'name': 'citation_issn'})
    if meta_issn:
        val = meta_issn.get('content', '').strip()
        if ISSN_RE.match(val):
            # Can't tell if print or electronic from meta alone, store as generic candidate
            issn_electronic = val  # Most sites expose eISSN in meta

    # DC.Identifier with scheme ISSN
    for meta in soup.find_all('meta', attrs={'name': 'DC.Identifier'}):
        content = meta.get('content', '').strip()
        if ISSN_RE.match(content):
            issn_electronic = content

    # --- Strategy 2: SciELO specific patterns ---
    # SciELO uses label elements: "Versão impressa ISSN:" followed by the number
    all_text_nodes = list(soup.stripped_strings)
    
    for i, text in enumerate(all_text_nodes):
        text_lower = text.lower().strip()
        
        # SciELO: label is one element, value is next
        if 'versão impressa issn' in text_lower or 'print version issn' in text_lower:
            # ISSN is in the next text node
            if i + 1 < len(all_text_nodes):
                m = ISSN_RE.search(all_text_nodes[i + 1])
                if m:
                    issn_print = m.group(1)
            # Or in the same node
            m = ISSN_RE.search(text)
            if m and not issn_print:
                issn_print = m.group(1)
                
        if 'versão on-line issn' in text_lower or 'versão online issn' in text_lower or 'online version issn' in text_lower:
            if i + 1 < len(all_text_nodes):
                m = ISSN_RE.search(all_text_nodes[i + 1])
                if m:
                    issn_electronic = m.group(1)
            m = ISSN_RE.search(text)
            if m and not issn_electronic:
                issn_electronic = m.group(1)
    
    # --- Strategy 3: Free text patterns ---
    full_text = soup.get_text()
    
    # Print ISSN patterns
    if not issn_print:
        patterns_print = [
            r'ISSN\s*(?:Impresso|print|impresso)\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'(?:Print|Impresso)\s*ISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'ISSN\s*print\s*(\d{4}-\d{3}[\dXx])',
            r'pISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'\(ISSN\s*print\s*(\d{4}-\d{3}[\dXx])\)',
        ]
        for pattern in patterns_print:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                issn_print = m.group(1)
                break
    
    # Electronic ISSN patterns
    if not issn_electronic:
        patterns_elec = [
            r'ISSN\s*(?:Eletrônico|Eletronico|Electronic|eletrônico|eletronico|electronic|Online|online|On-?line|on-?line)\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'(?:Electronic|Eletrônico|Eletronico|Online|On-?line)\s*ISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'eISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'e-ISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])',
            r'ISSN\s*[:\s]*(\d{4}-\d{3}[\dXx])\s*\(?(?:online|eletrônico|electronic)',
        ]
        for pattern in patterns_elec:
            m = re.search(pattern, full_text, re.IGNORECASE)
            if m:
                issn_electronic = m.group(1)
                break

    # --- Strategy 4: Generic ISSN extraction ---
    # If we found one but not both, look for all ISSNs and take the other
    all_issns = list(set(ISSN_RE.findall(full_text)))
    
    if not issn_print and not issn_electronic and len(all_issns) == 1:
        # Only one ISSN found, can't determine type - store as electronic (more common)
        issn_electronic = all_issns[0]
    elif len(all_issns) == 2:
        if not issn_print and not issn_electronic:
            # SciELO convention: first is usually print
            issn_print = all_issns[0]
            issn_electronic = all_issns[1]
        elif issn_print and not issn_electronic:
            other = [x for x in all_issns if x != issn_print]
            if other:
                issn_electronic = other[0]
        elif issn_electronic and not issn_print:
            other = [x for x in all_issns if x != issn_electronic]
            if other:
                issn_print = other[0]

    return issn_print, issn_electronic


def fetch_page(url):
    """Fetch a URL and return BeautifulSoup, or None on error."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code == 200:
            return BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        pass
    return None


def get_about_url(url, source_type):
    """Generate the /about URL based on source type."""
    url = url.rstrip('/')
    if source_type == 'scielo':
        return url + '/about/'
    else:
        # OJS: /about or /about/aboutJournal
        return url + '/about'


def process_journal(journal):
    """Try to extract ISSNs for a journal."""
    need_print = not journal.issn_print
    need_elec = not journal.issn_electronic
    
    if not need_print and not need_elec:
        return False  # Nothing to do
    
    url = journal.url
    if not url or url == 'TODO_ENTER_URL_HERE':
        return False
    
    found_print = None
    found_elec = None
    
    # Try main page
    soup = fetch_page(url)
    if soup:
        found_print, found_elec = extract_issn_from_soup(soup)
    
    # If still missing, try /about page
    if (need_print and not found_print) or (need_elec and not found_elec):
        about_url = get_about_url(url, journal.source_type)
        soup_about = fetch_page(about_url)
        if soup_about:
            about_print, about_elec = extract_issn_from_soup(soup_about)
            if not found_print:
                found_print = about_print
            if not found_elec:
                found_elec = about_elec
    
    # Update journal
    updated = False
    if need_print and found_print:
        journal.issn_print = found_print
        updated = True
    if need_elec and found_elec:
        journal.issn_electronic = found_elec
        updated = True
    
    return updated


def main():
    session = get_session()
    
    # Get journals missing at least one ISSN
    journals = session.query(Journal).filter(
        (Journal.issn_print == None) | (Journal.issn_electronic == None)
    ).order_by(Journal.id).all()
    
    total = len(journals)
    print(f"Found {total} journals missing ISSN data\n")
    
    updated_count = 0
    error_count = 0
    skipped_count = 0
    
    for i, journal in enumerate(journals, 1):
        prefix = f"[{i}/{total}]"
        
        if not journal.url or journal.url == 'TODO_ENTER_URL_HERE':
            print(f"{prefix} SKIP {journal.name} (no URL)")
            skipped_count += 1
            continue
        
        print(f"{prefix} Processing: {journal.name}")
        print(f"        URL: {journal.url}")
        print(f"        Before: print={journal.issn_print} | elec={journal.issn_electronic}")
        
        try:
            updated = process_journal(journal)
            
            if updated:
                session.commit()
                updated_count += 1
                print(f"        ✅ Updated: print={journal.issn_print} | elec={journal.issn_electronic}")
            else:
                print(f"        ⚠️  No ISSN found")
                
        except Exception as e:
            error_count += 1
            print(f"        ❌ Error: {e}")
            session.rollback()
        
        # Be polite to servers
        time.sleep(0.5)
    
    print(f"\n{'='*60}")
    print(f"RESULTS:")
    print(f"  Total processed: {total}")
    print(f"  Updated:         {updated_count}")
    print(f"  No data found:   {total - updated_count - error_count - skipped_count}")
    print(f"  Errors:          {error_count}")
    print(f"  Skipped:         {skipped_count}")
    
    # Show remaining missing
    still_missing_print = session.query(Journal).filter(Journal.issn_print == None).count()
    still_missing_elec = session.query(Journal).filter(Journal.issn_electronic == None).count()
    print(f"\n  Still missing ISSN Print:      {still_missing_print}")
    print(f"  Still missing ISSN Electronic: {still_missing_elec}")


if __name__ == '__main__':
    main()
