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

        soup = self.get_soup(archive_url)
        if not soup:
            # Fallback to base url if /issue/archive fails
            soup = self.get_soup(self.base_url)
            if not soup:
                return []

        issue_items = []
        seen_urls = set()
        
        items_on_page = self._scrape_issues_from_page(soup, archive_url)
        for it in items_on_page:
            if it['url'] not in seen_urls:
                seen_urls.add(it['url'])
                issue_items.append(it)
        
        # Simple loop for next pages
        current_soup = soup
        page = 1
        max_pages = 50
        while page < max_pages:
            next_link_node = current_soup.find('a', class_='next')
            if next_link_node and next_link_node.get('href'):
                next_url = urljoin(archive_url, next_link_node.get('href'))
                current_soup = self.get_soup(next_url)
                if current_soup:
                    new_items = self._scrape_issues_from_page(current_soup, next_url)
                    if not new_items:
                        break
                    for it in new_items:
                        if it['url'] not in seen_urls:
                            seen_urls.add(it['url'])
                            issue_items.append(it)
                    page += 1
                else:
                    break
            else:
                break

        return issue_items

    def _scrape_issues_from_page(self, soup, current_url):
        base_host = urlparse(self.base_url).netloc.lower()
        issues = []
        seen_urls = set()

        # Method 1: Look for structured issue blocks (OJS 3 obj_issue_summary, issue-summary, issue_toc)
        issue_blocks = soup.find_all('div', class_=re.compile(r'obj_issue_summary|issue-summary|issue_toc'))
        if issue_blocks:
            for b in issue_blocks:
                title_el = b.find('a', class_='title') or b.find('h2') or b.find('h3') or b.find('a')
                if not title_el:
                    continue
                a_tag = title_el if title_el.name == 'a' else title_el.find('a')
                if not a_tag or not a_tag.get('href'):
                    continue
                href = a_tag['href'].strip()
                if '/issue/view/' not in href:
                    continue
                full_url = urljoin(current_url, href).split('#')[0]
                if urlparse(full_url).netloc.lower() != base_host or full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                title_text = a_tag.get_text(' ', strip=True)
                series_el = b.find('div', class_=re.compile(r'series|lead'))
                series_text = series_el.get_text(' ', strip=True) if series_el else ''
                full_title = f"{title_text} ({series_text})" if series_text and series_text not in title_text else title_text

                # Parse year, vol, num
                year_m = re.search(r'(?:19|20)\d{2}', full_title)
                year = year_m.group(0) if year_m else None
                vol_m = re.search(r'v\.\s*(\d+)', full_title, re.I)
                vol = vol_m.group(1) if vol_m else None
                num_m = re.search(r'n\.\s*([0-9\s\w]+)', full_title, re.I)
                num = num_m.group(1).strip() if num_m else None

                issues.append({
                    'url': full_url,
                    'title': full_title or 'Edição sem título',
                    'year': year,
                    'volume': vol,
                    'number': num
                })

        # Method 2: Generic link scan for any issue/view/ link
        for a in soup.find_all('a', href=True):
            href = a['href'].strip()
            if '/issue/view/' in href:
                full_url = urljoin(current_url, href).split('#')[0]
                if urlparse(full_url).netloc.lower() != base_host or full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                title_text = a.get_text(' ', strip=True)
                
                year_m = re.search(r'(?:19|20)\d{2}', title_text)
                year = year_m.group(0) if year_m else None
                vol_m = re.search(r'v\.\s*(\d+)', title_text, re.I)
                vol = vol_m.group(1) if vol_m else None
                num_m = re.search(r'n\.\s*([0-9\s\w]+)', title_text, re.I)
                num = num_m.group(1).strip() if num_m else None

                issues.append({
                    'url': full_url,
                    'title': title_text or 'Edição sem título',
                    'year': year,
                    'volume': vol,
                    'number': num
                })

        return issues

    def get_issue_metadata(self, issue_url):
        soup = self.get_soup(issue_url)
        if not soup:
            return {}
        h1 = soup.find('h1') or soup.find('h2')
        title_text = h1.get_text(' ', strip=True) if h1 else ''
        year_m = re.search(r'(?:19|20)\d{2}', title_text)
        year = year_m.group(0) if year_m else None
        vol_m = re.search(r'v\.\s*(\d+)', title_text, re.I)
        vol = vol_m.group(1) if vol_m else None
        num_m = re.search(r'n\.\s*([0-9\s\w]+)', title_text, re.I)
        num = num_m.group(1).strip() if num_m else None
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
            if '/article/view/' in href:
                full_url = urljoin(issue_url, href)
                # Ensure article belongs strictly to the same domain as the journal
                if urlparse(full_url).netloc.lower() != base_host:
                    continue
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
        try:
            if self.agent_type == 'rotate':
                self.session.headers.update(get_headers('rotate'))
            response = self.session.get(article_url, timeout=(4, 12))
            response.raise_for_status()
            html_text = response.text
        except Exception:
            return None

        # 1. FAST-PATH: Try regex extraction on HTML head (0.001s vs 50ms)
        pdf_match = re.search(r'<meta\s+name=[\"\']citation_pdf_url[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not pdf_match:
            pdf_match = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_pdf_url[\"\']', html_text, re.I)

        title_match = re.search(r'<meta\s+name=[\"\']citation_title[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not title_match:
            title_match = re.search(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_title[\"\']', html_text, re.I)

        author_matches = re.findall(r'<meta\s+name=[\"\']citation_author[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not author_matches:
            author_matches = re.findall(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_author[\"\']', html_text, re.I)

        # Extract metadata author emails (OJS citation_author_email and mailto:)
        page_emails = re.findall(r'<meta\s+name=[\"\']citation_author_email[\"\']\s+content=[\"\']([^\"\']+)[\"\']', html_text, re.I)
        if not page_emails:
            page_emails = re.findall(r'<meta\s+content=[\"\']([^\"\']+)[\"\']\s+name=[\"\']citation_author_email[\"\']', html_text, re.I)
        mailto_matches = re.findall(r'href=[\"\']mailto:([^\"\'\?]+)', html_text, re.I)
        all_meta_emails = list(set([e.strip().lower() for e in (page_emails + mailto_matches) if '@' in e and '.' in e]))

        if pdf_match:
            raw_pdf_url = pdf_match.group(1).strip()
            full_pdf_url = urljoin(article_url, raw_pdf_url)
            if '/view/' in full_pdf_url and '/download/' not in full_pdf_url:
                download_url = full_pdf_url.replace('/view/', '/download/')
            else:
                download_url = full_pdf_url
            
            title = title_match.group(1).strip() if title_match else "Unknown Title"
            authors = ", ".join([a.strip() for a in author_matches]) if author_matches else "Unknown Authors"
            filename = self.generate_filename(download_url, article_url)

            return {
                'journal': self.journal_name,
                'issue_url': article_url,
                'article_title': title,
                'article_url': article_url,
                'authors': authors,
                'pdf_url': download_url,
                'pdf_filename': filename,
                'emails': all_meta_emails
            }

        # 2. SLOW-PATH: Fallback to BeautifulSoup for non-standard templates
        soup = BeautifulSoup(html_text, 'html.parser')

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

        # Fallback PDF search
        pdf_url = None
        pdf_link = soup.find('a', class_='obj_galley_link pdf')
        if not pdf_link:
             pdf_link = soup.find('a', attrs={'href': re.compile(r'/article/view/\d+/\d+')})
        if not pdf_link:
             pdf_link = soup.find('a', string=re.compile(r'PDF', re.I))

        if pdf_link and pdf_link.get('href'):
             raw_url = pdf_link['href'].strip()
             full_url = urljoin(article_url, raw_url)
             if '/view/' in full_url and '/download/' not in full_url:
                  pdf_url = full_url.replace('/view/', '/download/')
             else:
                  pdf_url = full_url

        filename = self.generate_filename(pdf_url, article_url) if pdf_url else None

        return {
            'journal': self.journal_name,
            'issue_url': article_url,
            'article_title': title,
            'article_url': article_url,
            'authors': authors,
            'pdf_url': pdf_url,
            'pdf_filename': filename,
            'emails': all_meta_emails
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
