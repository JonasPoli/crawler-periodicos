import requests
from bs4 import BeautifulSoup
from database import get_session, Article, Journal, Edition
import random

def inspect_articles(num_articles=3):
    session = get_session()
    
    # Get a few random articles that have a URL
    articles = session.query(Article).filter(Article.url.isnot(None)).all()
    
    if not articles:
        print("No articles with URLs found.")
        return

    selected = random.sample(articles, min(len(articles), num_articles))
    
    print(f"Inspecting {len(selected)} articles...\n")
    
    for article in selected:
        print(f"--- Article ID: {article.id} ---")
        print(f"Title: {article.title}")
        print(f"URL: {article.url}")
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            response = requests.get(article.url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Check for OJS common meta tags
                print("\n[Meta Tags - Common OJS/Scholar]")
                meta_names = [
                    'citation_title', 
                    'citation_date', 
                    'citation_author', 
                    'citation_pdf_url',
                    'citation_doi',
                    'citation_keywords',
                    'citation_firstpage',
                    'citation_lastpage'
                ]
                
                for name in meta_names:
                    tags = []
                    for tag in soup.find_all('meta', attrs={'name': name}):
                         tags.append(tag.get('content'))
                    if tags:
                        print(f"  {name}: {tags}")

                # Special check for abstract to see langs
                print("  [Abstracts]")
                for tag in soup.find_all('meta', attrs={'name': 'citation_abstract'}):
                    print(f"    - Content: {tag.get('content')[:50]}... | Lang: {tag.get('xml:lang')}")

                # Check for User's specific snippets
                print("\n[HTML Structure Checks]")
                
                # Dates
                print("  Dates:")
                date_submitted = soup.find('div', class_='item date_submitted')
                print(f"    Submitted: {'Yes' if date_submitted else 'No'}")
                date_published = soup.find('div', class_='item date_published')
                print(f"    Published: {'Yes' if date_published else 'No'}")
                
                # License
                print("  License:")
                license_url = soup.find('a', rel='license')
                print(f"    License URL: {license_url['href'] if license_url else 'No'}")
                
                # Journal Metadata (often in footer or sidebar)
                print("  Journal Metadata:")
                issn_print = soup.find(string=re.compile(r'ISSN.*Impresso|Print.*ISSN', re.IGNORECASE))
                print(f"    ISSN Print found: {'Yes' if issn_print else 'No'}")
                issn_elec = soup.find(string=re.compile(r'ISSN.*Eletrônico|Electronic.*ISSN', re.IGNORECASE))
                print(f"    ISSN Electronic found: {'Yes' if issn_elec else 'No'}")
                
                # Contact info usually in sidebar "Contact" or footer
                print("    Address/Phone/Email indicators (text search):")
                has_email = soup.find(string=re.compile(r'@'))
                print(f"      Email-like text: {'Yes' if has_email else 'No'}")
                
                # Article Metadata
                print("  Article Metadata:")
                pages = soup.find(string=re.compile(r'Páginas|Pages'))
                print(f"    Pages indicator: {'Yes' if pages else 'No'}")
                
                acceptance = soup.find('div', class_='item date_accepted')
                print(f"    Accepted Date: {'Yes' if acceptance else 'No'}")
                
                authors_section = soup.find('section', class_='item authors')
                if authors_section:
                    print(f"  Found <section class='item authors'>: Yes")
                else:
                    print(f"  Found <section class='item authors'>: No")

                keywords_section = soup.find('section', class_='item keywords')
                if keywords_section:
                     print(f"  Found <section class='item keywords'>: Yes")
                else:
                    print(f"  Found <section class='item keywords'>: No")

                refs_section = soup.find('section', class_='item references')
                if refs_section:
                     print(f"  Found <section class='item references'>: Yes")
                else:
                    print(f"  Found <section class='item references'>: No")
                    
            else:
                print(f"Failed to fetch content. Status code: {response.status_code}")
                
        except Exception as e:
            print(f"Error fetching/parsing: {e}")
        
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    inspect_articles()
