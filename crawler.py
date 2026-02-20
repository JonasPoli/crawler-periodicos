import os
import requests
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin

class Crawler:
    def __init__(self, base_url, download_dir='downloads'):
        self.base_url = base_url
        self.download_dir = download_dir
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

    def get_all_archive_issues(self, base_archive_url):
        all_issues = []
        page = 1
        while True:
            # First page is just /archive, subsequent are /archive/N
            url = base_archive_url if page == 1 else f"{base_archive_url}/{page}"
            print(f"Fetching archive page {page}: {url}")
            issues = self.get_issues(url)
            
            if not issues:
                print(f"No issues found on page {page}. Stopping archive search.")
                break
                
            new_issues = [i for i in issues if i not in all_issues]
            if not new_issues:
                print(f"No new issues found on page {page}. Stopping.")
                break
                
            all_issues.extend(new_issues)
            page += 1
            
        return all_issues

    def get_issues(self, archive_url):
        soup = self.get_soup(archive_url)
        if not soup:
            return []

        issue_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            # User wants destination URLs like issue/view/110
            if '/issue/view/' in href and href not in issue_links:
                issue_links.append(href)
        
        return list(set(issue_links))

    def get_articles(self, issue_url):
        print(f"Fetching issue: {issue_url}")
        soup = self.get_soup(issue_url)
        if not soup:
            return []

        article_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/article/view/' in href and '/pdf' not in href and href not in article_links:
                 article_links.append(href)
        
        return list(set(article_links))

    def get_pdf_link(self, article_url):
        soup = self.get_soup(article_url)
        if not soup:
            return None

        # User specifically asked to open buttons that have the text "PDF"
        # First pass: Look for direct "PDF" text in the link
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text().strip()
            
            # Use strict "PDF" check or "PDF" in text
            if 'PDF' in text or 'pdf' in text.lower():
                 if '/article/view/' in href or '/article/download/' in href:
                     # Identify if it's a view link that needs conversion or a download link
                     return href
            
            # Check for classnames if text fails
            if 'pdf' in str(a.get('class')):
                return href

        # Fallback to existing logic if simple text search fails
        for a in soup.find_all('a', href=True):
            href = a['href']
            if '/article/view/' in href and '/1' in href: 
                 return href

        return None

    def download_pdf(self, pdf_view_url):
        # OJS often has a view page vs a direct download link.
        # Sometimes the 'view' URL redirects to download or embeds it.
        # We need to check if it's a view page or direct download.
        
        # Often OJS requires converting /view/ to /download/
        download_url = pdf_view_url.replace('/view/', '/download/')
        
        try:
            local_filename = f"{self.download_dir}/{download_url.split('/')[-2]}_{download_url.split('/')[-1]}.pdf"
            if os.path.exists(local_filename):
                 # print(f"Skipping existing: {local_filename}")
                 return local_filename

            print(f"Downloading: {download_url}")
            with self.session.get(download_url, stream=True) as r:
                r.raise_for_status()
                with open(local_filename, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            time.sleep(1) # Respect server
            return local_filename
        except Exception as e:
            print(f"Failed to download {download_url}: {e}")
            return None
