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

class OJSCrawler:
    def __init__(self, base_url, journal_name, download_dir='downloads_ojs', metadata_manager=None, db_manager=None, force=False, agent_type='rotate'):
        self.raw_url = base_url.strip()
        self.base_url = self._normalize_base_url(self.raw_url)
        self.journal_name = journal_name
        self.download_dir = download_dir
        self.metadata_manager = metadata_manager
        self.db_manager = db_manager
        self.force = force
        self.agent_type = agent_type
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)
            
        self.session = create_configured_session(agent_type=self.agent_type, pool_size=20)

    def _normalize_base_url(self, url):
        """Clean journal base URL by removing /issue/archive, /issue/current, trailing slashes."""
        u = url.strip()
        # Remove issue suffixes
        u = re.sub(r'/issue/(archive|current|view/.*)$', '', u, flags=re.IGNORECASE)
        return u.rstrip('/')

    def get_soup(self, url):
        try:
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
            response = self.session.get(url, timeout=12)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            # print(f"Error fetching {url}: {e}")
            return None

    def get_all_issues(self):
        # Determine archive url
        if '/issue/archive' in self.raw_url.lower():
            archive_url = self.raw_url
        else:
            archive_url = f"{self.base_url}/issue/archive"

        # print(f"Fetching archive: {archive_url}")
        soup = self.get_soup(archive_url)
        if not soup:
            # Fallback to base url if /issue/archive fails
            soup = self.get_soup(self.base_url)
            if not soup:
                return []

        issue_links = []
        urls_on_page = self._scrape_issues_from_page(soup, archive_url)
        issue_links.extend(urls_on_page)
        
        # Simple loop for next pages
        current_soup = soup
        page = 1
        max_pages = 50
        while page < max_pages:
            next_link_node = current_soup.find('a', class_='next')
            if next_link_node and next_link_node.get('href'):
                next_url = urljoin(archive_url, next_link_node.get('href'))
                # print(f"  Fetching next archive page: {next_url}")
                current_soup = self.get_soup(next_url)
                if current_soup:
                    new_links = self._scrape_issues_from_page(current_soup, next_url)
                    if not new_links:
                        break
                    issue_links.extend(new_links)
                    page += 1
                else:
                    break
            else:
                break

        return list(set(issue_links))

    def _scrape_issues_from_page(self, soup, current_url):
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/issue/view/' in href:
                full_url = urljoin(current_url, href)
                # Remove query strings/fragments for clean issue canonical URL
                clean_url = full_url.split('#')[0]
                if clean_url not in links:
                    links.append(clean_url)
        return links

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
            if '/article/view/' in href:
                full_url = urljoin(issue_url, href)
                parts = full_url.split('/article/view/')
                if len(parts) > 1:
                    suffix = parts[1].split('?')[0].split('#')[0].rstrip('/')
                    # Landing page only (not direct galley view unless it's the only one)
                    if '/' not in suffix:
                        clean_url = f"{parts[0]}/article/view/{suffix}"
                        if clean_url not in article_links:
                            article_links.append(clean_url)
        return article_links

    def process_article(self, article_url):
        meta = self.fetch_article_metadata(article_url)
        if not meta: return

        pdf_url = meta.get('pdf_url')
        filename = meta.get('pdf_filename')
        
        if pdf_url:
            try:
                local_path = self.download_pdf_direct(pdf_url, filename)
                if local_path and self.metadata_manager:
                    self.metadata_manager.save_metadata(meta)
                if local_path and self.db_manager:
                    self.db_manager.mark_article_completed_by_url(article_url)
            except Exception as e:
                pass

    def fetch_article_metadata(self, article_url):
        soup = self.get_soup(article_url)
        if not soup:
            return None

        title = "Unknown Title"
        meta_title = soup.find('meta', attrs={'name': 'citation_title'})
        if meta_title and meta_title.get('content', '').strip():
             title = meta_title['content'].strip()
        else:
             h1 = soup.find('h1', class_='page_title')
             if h1: 
                 title = h1.get_text(strip=True)
             else:
                 h1 = soup.find('h1')
                 if h1: title = h1.get_text(strip=True)
        
        authors = "Unknown Authors"
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
        else:
            galley = soup.find('a', class_=lambda c: c and 'obj_galley_link' in c and 'pdf' in c)
            if galley and galley.get('href'):
                pdf_url = galley['href'].strip()
            else:
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True).upper()
                    if 'PDF' in text and '/article/view/' in a['href']:
                        pdf_url = a['href'].strip()
                        break
        
        download_url = None
        filename = None

        if pdf_url:
            full_pdf_url = urljoin(article_url, pdf_url)
            if '/view/' in full_pdf_url and '/download/' not in full_pdf_url:
                download_url = full_pdf_url.replace('/view/', '/download/')
            else:
                download_url = full_pdf_url
            
            filename = self.generate_filename(download_url, article_url)

        return {
            'journal': self.journal_name,
            'issue_url': article_url,
            'article_title': title,
            'article_url': article_url,
            'authors': authors,
            'pdf_url': download_url,
            'pdf_filename': filename
        }

    def generate_filename(self, download_url, article_url=None):
        """Deterministic filename generation to prevent duplicate downloads."""
        if '/download/' in download_url:
            try:
                parts = download_url.split('/download/')
                if len(parts) > 1:
                    ids = parts[1].split('?')[0].replace('/', '_').strip('_')
                    if ids:
                        return f"ojs_{ids}.pdf"
            except:
                pass
        elif '/view/' in download_url:
            try:
                parts = download_url.split('/view/')
                if len(parts) > 1:
                    ids = parts[1].split('?')[0].replace('/', '_').strip('_')
                    if ids:
                        return f"ojs_{ids}.pdf"
            except:
                pass

        # Deterministic fallback based on URL hash (NEVER random timestamp)
        target = article_url or download_url
        url_hash = hashlib.md5(target.encode('utf-8')).hexdigest()[:16]
        return f"ojs_{url_hash}.pdf"

    def download_pdf_direct(self, pdf_url, filename):
        if not pdf_url or not filename:
            return None
        local_path = os.path.join(self.download_dir, filename)
        if not self.force and os.path.exists(local_path) and os.path.getsize(local_path) > 1000:
            return local_path
            
        try:
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
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
