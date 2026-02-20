import os
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
from metadata_manager import MetadataManager

class SciELOCrawler:
    def __init__(self, base_url, journal_name, download_dir='downloads_scielo', metadata_manager=None, db_manager=None, force=False):
        self.base_url = base_url
        self.journal_name = journal_name
        self.download_dir = download_dir
        self.metadata_manager = metadata_manager
        self.db_manager = db_manager
        self.force = force
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        })

    def get_soup(self, url):
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None

    def get_all_issues(self):
        # Grid page: https://www.scielo.br/j/[acronym]/grid
        grid_url = f"{self.base_url}/grid"
        print(f"Fetching grid: {grid_url}")
        soup = self.get_soup(grid_url)
        if not soup:
            return []

        issue_links = []
        base_path = self.base_url.replace("https://www.scielo.br", "")
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/i/' in href and base_path in href:
                if href.startswith('/'):
                    href = f"https://www.scielo.br{href}"
                issue_links.append(href)
        
        return list(set(issue_links))

    def process_issue(self, issue_url):
        print(f"Processing issue: {issue_url}")
        article_links = self.get_article_urls(issue_url)
        print(f"  Found {len(article_links)} potential article links.")
        
        # Verify deduplication for language... 
        # Often SciELO links to same article in en/pt/es. 
        # Visiting all is fine, we just want to ensure we get the metadata.
        
        for art_url in article_links:
            if not self.force and self.db_manager and self.db_manager.is_article_completed(art_url):
                print(f"  Skipping completed article: {art_url}")
                continue
            self.process_article(art_url)

    def get_article_urls(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return []

        # Find links to ARTICLES (abstracts/texts), not just PDFs
        # Pattern: /j/rap/a/[ID]/...
        article_links = []
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            # We want the text/abstract page. Usually doesn't have 'format=pdf'
            if '/a/' in href and 'format=pdf' not in href:
                full_url = href
                if full_url.startswith('/'):
                    full_url = f"https://www.scielo.br{full_url}"
                
                # Deduplicate
                if full_url not in article_links:
                    article_links.append(full_url)
        return article_links

    def process_article(self, article_url):
        meta = self.fetch_article_metadata(article_url)
        if not meta: return
        
        pdf_url = meta.get('pdf_url')
        filename = meta.get('pdf_filename')

        if pdf_url:
            local_path = self.download_pdf_direct(pdf_url, filename)
            
            # Only save metadata (and file record) if we actually have the file (downloaded or existed)
            if local_path and self.metadata_manager:
                self.metadata_manager.save_metadata(meta)
            
            # Mark as completed in DB if download successful (or skipped as existing)
            if local_path and self.db_manager:
                self.db_manager.mark_article_completed_by_url(article_url)

    def fetch_article_metadata(self, article_url):
        soup = self.get_soup(article_url)
        if not soup:
            return None

        # Use Standard Meta Tags (Dublin Core / Google Scholar)
        title = "Unknown Title"
        authors = "Unknown Authors"
        
        # Title
        meta_title = soup.find('meta', attrs={'name': 'citation_title'})
        if meta_title:
            title = meta_title['content']
            
        # Authors
        meta_authors = []
        for meta in soup.find_all('meta', attrs={'name': 'citation_author'}):
            meta_authors.append(meta['content'])
        if meta_authors:
            authors = ", ".join(meta_authors)

        # PDF Link
        pdf_url = None
        pdf_meta = soup.find('meta', attrs={'name': 'citation_pdf_url'})
        if pdf_meta:
            pdf_url = pdf_meta['content']
        
        filename = None
        if pdf_url:
             filename = self.generate_filename(pdf_url)

        return {
            'journal': self.journal_name,
            'issue_url': article_url,
            'article_title': title,
            'article_url': article_url,
            'authors': authors,
            'pdf_url': pdf_url,
            'pdf_filename': filename
        }

    def generate_filename(self, pdf_url):
        # Determine lang from PDF url if possible
        lang = 'unknown'
        if 'lang=en' in pdf_url: lang = 'en'
        elif 'lang=pt' in pdf_url: lang = 'pt'
        elif 'lang=es' in pdf_url: lang = 'es'

        # Filename
        if '/a/' in pdf_url:
            try:
                parts = pdf_url.split('/a/')[1].split('/')
                article_id = parts[0]
                filename = f"{article_id}_{lang}.pdf"
            except:
                    filename = f"scielo_{int(time.time())}.pdf"
        else:
            filename = f"scielo_{int(time.time())}.pdf"
        return filename

    def download_pdf_direct(self, pdf_url, filename):
        local_path = os.path.join(self.download_dir, filename)
        if not self.force and os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
            # print(f"Skipping existing (valid): {filename}")
            return local_path
            
        print(f"Downloading: {pdf_url}")
        try:
            with self.session.get(pdf_url, stream=True) as r:
                r.raise_for_status()
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            time.sleep(1)
            return local_path
        except Exception as e:
            print(f"Failed to download {pdf_url}: {e}")
            return None
    
    def download_pdf(self, pdf_url, filename):
        return self.download_pdf_direct(pdf_url, filename)
