import os
import re
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
from metadata_manager import MetadataManager

class SciELOCrawler:
    def __init__(self, base_url, journal_name, download_dir='downloads_scielo', metadata_manager=None, db_manager=None, force=False):
        self.base_url = base_url.strip().rstrip('/')
        self.journal_name = journal_name
        self.download_dir = download_dir
        self.metadata_manager = metadata_manager
        self.db_manager = db_manager
        self.force = force
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)
            
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=0.3, status_forcelist=[502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=20)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def get_soup(self, url):
        try:
            response = self.session.get(url, timeout=12)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            return None

    def get_all_issues(self):
        grid_url = f"{self.base_url}/grid"
        soup = self.get_soup(grid_url)
        if not soup:
            return []

        issue_links = []
        base_path = self.base_url.replace("https://www.scielo.br", "").replace("http://www.scielo.br", "")
        
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/i/' in href and (not base_path or base_path in href):
                full_url = urljoin(self.base_url, href)
                if full_url not in issue_links:
                    issue_links.append(full_url)
        
        return list(set(issue_links))

    def process_issue(self, issue_url):
        article_links = self.get_article_urls(issue_url)
        for art_url in article_links:
            if not self.force and self.db_manager and self.db_manager.is_article_completed(art_url):
                continue
            self.process_article(art_url)

    def get_article_urls(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return []

        article_links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/a/' in href and 'format=pdf' not in href:
                full_url = urljoin(issue_url, href).split('?')[0].split('#')[0]
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
            if local_path and self.metadata_manager:
                self.metadata_manager.save_metadata(meta)
            if local_path and self.db_manager:
                self.db_manager.mark_article_completed_by_url(article_url)

    def fetch_article_metadata(self, article_url):
        soup = self.get_soup(article_url)
        if not soup:
            return None

        title = "Unknown Title"
        authors = "Unknown Authors"
        
        meta_title = soup.find('meta', attrs={'name': 'citation_title'})
        if meta_title and meta_title.get('content', '').strip():
            title = meta_title['content'].strip()
            
        meta_authors = []
        for meta in soup.find_all('meta', attrs={'name': 'citation_author'}):
            if meta.get('content', '').strip():
                meta_authors.append(meta['content'].strip())
        if meta_authors:
            authors = ", ".join(meta_authors)

        pdf_url = None
        pdf_meta = soup.find('meta', attrs={'name': 'citation_pdf_url'})
        if pdf_meta and pdf_meta.get('content', '').strip():
            pdf_url = pdf_meta['content'].strip()
        
        filename = None
        if pdf_url:
             full_pdf_url = urljoin(article_url, pdf_url)
             filename = self.generate_filename(full_pdf_url, article_url)
             pdf_url = full_pdf_url

        return {
            'journal': self.journal_name,
            'issue_url': article_url,
            'article_title': title,
            'article_url': article_url,
            'authors': authors,
            'pdf_url': pdf_url,
            'pdf_filename': filename
        }

    def generate_filename(self, pdf_url, article_url=None):
        lang = 'unknown'
        if 'lang=en' in pdf_url: lang = 'en'
        elif 'lang=pt' in pdf_url: lang = 'pt'
        elif 'lang=es' in pdf_url: lang = 'es'

        if '/a/' in pdf_url:
            try:
                parts = pdf_url.split('/a/')[1].split('/')
                article_id = parts[0]
                if article_id:
                    return f"scielo_{article_id}_{lang}.pdf"
            except:
                pass

        target = article_url or pdf_url
        url_hash = hashlib.md5(target.encode('utf-8')).hexdigest()[:16]
        return f"scielo_{url_hash}_{lang}.pdf"

    def download_pdf_direct(self, pdf_url, filename):
        if not pdf_url or not filename:
            return None
        local_path = os.path.join(self.download_dir, filename)
        if not self.force and os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
            return local_path
            
        try:
            with self.session.get(pdf_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
            return local_path
        except Exception as e:
            if os.path.exists(local_path) and os.path.getsize(local_path) < 1000:
                try: os.remove(local_path)
                except: pass
            return None
    
    def download_pdf(self, pdf_url, filename):
        return self.download_pdf_direct(pdf_url, filename)
