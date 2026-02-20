from database import get_session, Article
import requests
from bs4 import BeautifulSoup
from collections import Counter

def check_html_emails(limit=10):
    session = get_session()
    
    # Get random articles from OJS and SciELO
    # OJS usually has /article/view/
    # SciELO usually has /j/...
    
    # Let's pick some that are 'downloaded' or 'completed' but maybe failed email extraction?
    # Or just any.
    
    articles = session.query(Article).limit(limit).all()
    
    print(f"Checking {len(articles)} articles for HTML metadata emails...")
    
    stats = Counter()
    
    for article in articles:
        url = article.url
        print(f"\nChecking: {url}")
        
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                print(f"  Failed to fetch: {r.status_code}")
                stats['failed_fetch'] += 1
                continue
                
            soup = BeautifulSoup(r.content, 'html.parser')
            
            # Check meta tags
            emails = []
            # specific OJS / DC
            for meta in soup.find_all('meta', attrs={'name': 'citation_author_email'}):
                emails.append(meta['content'])
            
            # Also check visible mailtos?
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('mailto:'):
                    emails.append(href.replace('mailto:', '').split('?')[0])
            
            emails = list(set(emails))
            
            if emails:
                print(f"  FOUND EMAILS: {emails}")
                stats['found_emails'] += 1
            else:
                print("  No emails found in HTML.")
                stats['no_emails'] += 1
                
        except Exception as e:
            print(f"  Error: {e}")
            stats['error'] += 1
            
    print("\n--- Stats ---")
    print(stats)
    session.close()

if __name__ == "__main__":
    check_html_emails()
