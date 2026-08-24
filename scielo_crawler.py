import os
import re
import hashlib
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin, urlparse
from metadata_manager import MetadataManager
from user_agents import get_headers, create_configured_session

class SciELOCrawler:
    def __init__(self, base_url, journal_name, download_dir='downloads_scielo', metadata_manager=None, db_manager=None, force=False, agent_type='rotate'):
        self.base_url = base_url.strip().rstrip('/')
        self.journal_name = journal_name
        self.download_dir = download_dir
        self.metadata_manager = metadata_manager
        self.db_manager = db_manager
        self.force = force
        self.agent_type = agent_type
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)
            
        self.session = create_configured_session(agent_type=self.agent_type, pool_size=50)

    def get_soup(self, url):
        try:
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
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

        base_host = urlparse(self.base_url).netloc.lower()
        issue_items = []
        seen_urls = set()
        base_path = self.base_url.replace("https://www.scielo.br", "").replace("http://www.scielo.br", "")
        
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/i/' in href and (not base_path or base_path in href):
                full_url = urljoin(self.base_url, href).split('#')[0]
                if urlparse(full_url).netloc.lower() == base_host and full_url not in seen_urls:
                    seen_urls.add(full_url)
                    
                    title_text = a.get_text(' ', strip=True)
                    # Parse year, volume, number from SciELO pattern e.g. /i/2021.v34n2/
                    m = re.search(r'/i/(\d{4})\.?(?:v([0-9a-zA-Z]+))?\.?(?:n([0-9a-zA-Z\-]+)|(ahead|nahead|suppl\w*))?', href, re.I)
                    year = m.group(1) if m else None
                    vol = m.group(2) if m else None
                    num = (m.group(3) or m.group(4)) if m else None
                    
                    if not title_text or title_text == 'v.' or len(title_text) < 2:
                        parts = []
                        if vol: parts.append(f"v. {vol}")
                        if num: parts.append(f"n. {num}")
                        if year: parts.append(f"({year})")
                        title_text = " ".join(parts) if parts else (href.split('/i/')[-1].strip('/') or 'Edição SciELO')

                    issue_items.append({
                        'url': full_url,
                        'title': title_text,
                        'year': year,
                        'volume': vol,
                        'number': num
                    })
        
        return issue_items

    def get_issue_metadata(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return {}
        h1 = soup.find('h1') or soup.find('h2')
        title_text = h1.get_text(' ', strip=True) if h1 else ''
        m = re.search(r'/i/(\d{4})\.?(?:v([0-9a-zA-Z]+))?\.?(?:n([0-9a-zA-Z\-]+)|(ahead|nahead|suppl\w*))?', issue_url, re.I)
        year = m.group(1) if m else None
        vol = m.group(2) if m else None
        num = (m.group(3) or m.group(4)) if m else None
        return {
            'title': title_text,
            'year': year,
            'volume': vol,
            'number': num
        }

    def process_issue(self, issue_item):
        issue_url = issue_item.get('url') if isinstance(issue_item, dict) else issue_item
        article_links = self.get_article_urls(issue_url)
        for art_url in article_links:
            if not self.force and self.db_manager and self.db_manager.is_article_completed(art_url):
                continue
            self.process_article(art_url)

    def get_article_urls(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return []

        base_host = urlparse(self.base_url).netloc.lower()
        article_links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/a/' in href and 'format=pdf' not in href:
                full_url = urljoin(issue_url, href).split('?')[0].split('#')[0]
                if urlparse(full_url).netloc.lower() == base_host and full_url not in article_links:
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
        try:
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
            response = self.session.get(article_url, timeout=(4, 12))
            response.raise_for_status()
            html_text = response.text
        except Exception:
            return None

        # 1. Fast-Path Regex
        pdf_match = re.search(r'<meta\s+name=[\"\']citation_pdf_url[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not pdf_match:
            pdf_match = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_pdf_url[\"\']', html_text, re.I)

        title_match = re.search(r'<meta\s+name=[\"\']citation_title[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not title_match:
            title_match = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_title[\"\']', html_text, re.I)

        author_matches = re.findall(r'<meta\s+name=[\"\']citation_author[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not author_matches:
            author_matches = re.findall(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_author[\"\']', html_text, re.I)

        if pdf_match:
            pdf_url = urljoin(article_url, pdf_match.group(1).strip())
            title = title_match.group(1).strip() if title_match else "Unknown Title"
            authors = ", ".join([a.strip() for a in author_matches]) if author_matches else "Unknown Authors"
            filename = self.generate_filename(pdf_url, article_url)

            return {
                'journal': self.journal_name,
                'issue_url': article_url,
                'article_title': title,
                'article_url': article_url,
                'authors': authors,
                'pdf_url': pdf_url,
                'pdf_filename': filename
            }

        # 2. Slow-Path BeautifulSoup
        soup = BeautifulSoup(html_text, 'html.parser')

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
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
            with self.session.get(pdf_url, stream=True, timeout=(5, 20)) as r:
                r.raise_for_status()
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
            return local_path
        except Exception as e:
            if os.path.exists(local_path) and os.path.getsize(local_path) < 1000:
                try: os.remove(local_path)
                except: pass
            return None
    
    def download_pdf(self, pdf_url, filename):
        return self.download_pdf_direct(pdf_url, filename)
