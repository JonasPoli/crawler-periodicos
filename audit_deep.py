from database import get_session, Article, Journal
import requests
from bs4 import BeautifulSoup
import pdfplumber
import os
import random

def audit_deep():
    session = get_session()
    
    # Get 5 SciELO and 5 OJS
    scielo_arts = session.query(Article).join(Article.edition).join(Journal).filter(Journal.source_type == 'scielo', Article.status == 'downloaded').limit(50).all()
    ojs_arts = session.query(Article).join(Article.edition).join(Journal).filter(Journal.source_type == 'ojs', Article.status == 'downloaded').limit(50).all()
    
    # Shuffle and pick 5
    random.shuffle(scielo_arts)
    random.shuffle(ojs_arts)
    scielo_sample = scielo_arts[:5]
    ojs_sample = ojs_arts[:5]
    
    print("=== DEEP AUDIT REPORT ===")
    
    for label, sample in [("SciELO", scielo_sample), ("OJS", ojs_sample)]:
        print(f"\n--- Analyzing {label} ({len(sample)} samples) ---")
        
        for art in sample:
            print(f"\nID: {art.id} | URL: {art.url}")
            
            # 1. Check HTML
            try:
                r = requests.get(art.url, timeout=5)
                soup = BeautifulSoup(r.content, 'html.parser')
                emails = []
                for meta in soup.find_all('meta'):
                    if 'email' in meta.get('name', '').lower() or 'email' in meta.get('property', '').lower():
                         emails.append(meta['content'])
                print(f"  [HTML] Meta Emails: {emails}")
            except Exception as e:
                print(f"  [HTML] Error: {e}")
            
            # 2. Check PDF
            # Find file
            if not art.files:
                print("  [PDF] No file attached.")
                continue
                
            f = art.files[0]
            path = f.local_path
            
            if not path or not os.path.exists(path):
                print(f"  [PDF] Missing file at {path}")
                continue
                
            print(f"  [PDF] Analyzing {path}...")
            try:
                text_len = 0
                page_count = 0
                with pdfplumber.open(path) as pdf:
                    page_count = len(pdf.pages)
                    if page_count > 0:
                        page1 = pdf.pages[0]
                        text = page1.extract_text() or ""
                        text_len = len(text)
                        
                print(f"  [PDF] Pages: {page_count} | Page 1 Text Chars: {text_len}")
                if text_len < 100:
                    print("  [PDF] WARNING: Likely Scanned/Image PDF (Low text count)")
                else:
                    print("  [PDF] Text-based (Good for extraction)")
                    
            except Exception as e:
                print(f"  [PDF] Error reading: {e}")

    session.close()

if __name__ == "__main__":
    audit_deep()
