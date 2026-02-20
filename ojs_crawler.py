import os
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin
from metadata_manager import MetadataManager

class OJSCrawler:
    def __init__(self, base_url, journal_name, download_dir='downloads_ojs', metadata_manager=None, db_manager=None, force=False):
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
        archive_url = f"{self.base_url}/issue/archive"
        print(f"Fetching archive: {archive_url}")
        soup = self.get_soup(archive_url)
        if not soup:
            return []

        issue_links = []
        urls_on_page = self._scrape_issues_from_page(soup)
        issue_links.extend(urls_on_page)
        
        # Simple loop for next pages
        current_soup = soup
        page = 1
        while True: # Crawl all archive pages
            next_link_node = current_soup.find('a', class_='next')
            if next_link_node and next_link_node.get('href'):
                next_url = next_link_node.get('href')
                print(f"  Fetching next archive page: {next_url}")
                current_soup = self.get_soup(next_url)
                if current_soup:
                    new_links = self._scrape_issues_from_page(current_soup)
                    issue_links.extend(new_links)
                    page += 1
                else:
                    break
            else:
                break

        return list(set(issue_links))

    def _scrape_issues_from_page(self, soup):
        links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            # OJS issue link pattern
            if '/issue/view/' in href:
                 if href not in links:
                     links.append(href)
        return links

    def process_issue(self, issue_url):
        print(f"Processing issue: {issue_url}")
        article_links = self.get_article_urls(issue_url)
        print(f"  Found {len(article_links)} articles.")
        
        for art_url in article_links:
            if not self.force and self.db_manager and self.db_manager.is_article_completed(art_url):
                print(f"  Skipping completed article: {art_url}")
                continue
            self.process_article(art_url)

    def get_article_urls(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return []

        article_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/article/view/' in href:
                # Filter for landing pages vs galleys
                # Landing page: /article/view/ID
                # Galley: /article/view/ID/GALLEY
                
                parts = href.split('/article/view/')
                if len(parts) > 1:
                    suffix = parts[1]
                    # Sometimes suffix has query params? Strip them
                    suffix = suffix.split('?')[0]
                    
                    if '/' not in suffix:
                        if href not in article_links:
                            article_links.append(href)
        return article_links

    def process_article(self, article_url):
        # Legacy wrapper
        meta = self.fetch_article_metadata(article_url)
        if not meta: return

        pdf_url = meta.get('pdf_url')
        filename = meta.get('pdf_filename')
        
        if pdf_url:
            try:
                local_path = self.download_pdf_direct(pdf_url, filename)
                
                # Only save metadata (and file record) if we actually have the file (downloaded or existed)
                if local_path and self.metadata_manager:
                    self.metadata_manager.save_metadata(meta)

                if local_path and self.db_manager:
                    self.db_manager.mark_article_completed_by_url(article_url)
            except Exception as e:
                print(f"Error downloading {pdf_url}: {e}")

    def fetch_article_metadata(self, article_url):
        soup = self.get_soup(article_url)
        if not soup:
            return None

        # Metadata
        title = "Unknown Title"
        # Meta tag preferred
        meta_title = soup.find('meta', attrs={'name': 'citation_title'})
        if meta_title:
             title = meta_title['content']
        else:
             h1 = soup.find('h1')
             if h1: title = h1.get_text(strip=True)
        
        # Authors
        authors = "Unknown Authors"
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
        else:
            for a in soup.find_all('a', href=True):
                text = a.get_text(strip=True).upper()
                if 'PDF' in text:
                    pdf_url = a['href']
                    break
        
        download_url = None
        filename = None

        if pdf_url:
            if '/view/' in pdf_url and '/download/' not in pdf_url:
                download_url = pdf_url.replace('/view/', '/download/')
            else:
                download_url = pdf_url
            
            filename = self.generate_filename(download_url)

        return {
            'journal': self.journal_name,
            'issue_url': article_url,
            'article_title': title,
            'article_url': article_url,
            'authors': authors,
            'pdf_url': download_url,
            'pdf_filename': filename
        }

    def generate_filename(self, download_url):
        filename = f"ojs_{int(time.time())}.pdf"
        if '/download/' in download_url:
                try:
                    parts = download_url.split('/download/')
                    if len(parts) > 1:
                        ids = parts[1].replace('/', '_')
                        filename = f"{ids}.pdf"
                except:
                    pass
        elif '/view/' in download_url:
                try:
                    parts = download_url.split('/view/')
                    if len(parts) > 1:
                        ids = parts[1].replace('/', '_')
                        filename = f"{ids}.pdf"
                except:
                    pass
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
