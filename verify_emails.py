import sqlite3
import csv
import re
import dns.resolver
import smtplib
import time
from tqdm import tqdm
from datetime import datetime
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

DB_PATH = 'crawler.db'
CSV_PATH = 'emails.csv'
MAX_WORKERS = 50  # Number of threads

logging.basicConfig(filename='email_verification.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Thread-local storage for DNS resolver to avoid potential locking issues in stats/cache
thread_local = threading.local()

def get_resolver():
    if not hasattr(thread_local, "resolver"):
        thread_local.resolver = dns.resolver.Resolver()
        thread_local.resolver.timeout = 5
        thread_local.resolver.lifetime = 5
    return thread_local.resolver

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;") 
    return conn

def extract_email(text):
    if not text:
        return None
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    if match:
        return match.group(0)
    return None

def verify_email_worker(email, cached_domain_info=None):
    """
    Worker function to verify a single email.
    Returns: dict with verification results.
    Does NOT write to DB.
    """
    parts = email.split('@')
    if len(parts) != 2:
        return {'email': email, 'error': 'Invalid format'}
    
    domain = parts[1].lower()
    
    has_dns = False
    has_mx = False
    mx_records = []
    
    # Check cache first if provided (read-only access assumed safe or copied)
    if cached_domain_info and domain in cached_domain_info:
        has_dns, has_mx, mx_records = cached_domain_info[domain]
    else:
        # Perform DNS checks
        resolver = get_resolver()
        try:
            try:
                resolver.resolve(domain, 'A')
                has_dns = True
            except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.Timeout):
                pass

            answers = resolver.resolve(domain, 'MX')
            has_mx = True
            for rdata in answers:
                mx_records.append(str(rdata.exchange).rstrip('.'))
            mx_records.sort()
            
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            pass
        except Exception as e:
            # logging.error(f"DNS error for {domain}: {e}")
            pass

    domain_valid = has_dns
    mx_valid = has_mx
    smtp_valid = False
    final_status = 'invalid_domain'

    if mx_valid:
        # SMTP Check
        try:
            mx_server = mx_records[0]
            server = smtplib.SMTP(timeout=5)
            server.set_debuglevel(0)
            server.connect(mx_server)
            server.helo('validator.test')
            
            # Just check if connection is okay; some servers block MAIL/RCPT checks
            code, _ = server.ehlo()
            if code == 250:
                 # Try deeper check
                try:
                    server.mail('test@validator.test')
                    code_rcpt, _ = server.rcpt(email)
                    if code_rcpt == 250:
                        smtp_valid = True
                        final_status = 'valid'
                    elif code_rcpt >= 500:
                         final_status = 'invalid_mailbox'
                    else:
                         final_status = 'risky' # Grayscale / temporary error
                except:
                    final_status = 'risky' # Connected but failed at mail/rcpt
            else:
                 final_status = 'risky' # Connected but EHLO failed
            
            server.quit()
        except Exception:
            final_status = 'risky' # Connection failed/timeout

    return {
        'email': email,
        'domain': domain,
        'format_valid': True,
        'domain_valid': domain_valid,
        'mx_valid': mx_valid,
        'smtp_valid': smtp_valid,
        'final_status': final_status,
        'has_dns': has_dns,
        'has_mx': has_mx,
        'mx_records': mx_records
    }

def process_emails():
    print(f"Reading emails from {CSV_PATH}...")
    emails_to_process = set()
    
    # 1. Read CSV
    try:
        with open(CSV_PATH, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            email_idx = -1
            if header:
                for idx, col in enumerate(header):
                    if 'email' in col.lower():
                        email_idx = idx
                        break
            
            if email_idx == -1:
                print("Could not find 'Email' column in CSV.")
                return

            for row in reader:
                if len(row) > email_idx:
                    clean = extract_email(row[email_idx])
                    if clean:
                        emails_to_process.add(clean.lower())
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return

    print(f"Found {len(emails_to_process)} unique emails.")

    # 2. Filter out already processed
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT email FROM email_verifications")
    existing_emails = {row['email'] for row in cursor.fetchall()}
    
    emails_to_verify = list(emails_to_process - existing_emails)
    print(f"Already verified: {len(existing_emails)}. Remaining: {len(emails_to_verify)}.")
    conn.close()

    if not emails_to_verify:
        print("All emails already verified.")
        return

    # 3. Load Domain Cache (to pass to workers)
    # Note: We won't update cache in workers to avoid complexity. 
    # Workers return domain info, main thread updates DB.
    # But for read-heavy cache, it's useful.
    domain_cache = {} # Simple dict, no locks needed for read-only
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT domain, has_dns, has_mx, mx_records FROM email_domains")
    for row in cursor.fetchall():
        domain_cache[row['domain']] = (
            bool(row['has_dns']),
            bool(row['has_mx']),
            json.loads(row['mx_records']) if row['mx_records'] else []
        )
    conn.close()

    # 4. Process in Parallel
    print(f"Starting verification with {MAX_WORKERS} threads...")
    
    # Open DB connection for writing results
    conn = get_db_connection()
    cursor = conn.cursor()

    count = 0
    domains_updates = {} # Local buffer for domain updates to minimize DB hits

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_email = {executor.submit(verify_email_worker, email, domain_cache): email for email in emails_to_verify}
        
        for future in tqdm(as_completed(future_to_email), total=len(emails_to_verify)):
            email = future_to_email[future]
            try:
                result = future.result()
                if 'error' in result:
                    continue
                
                # Check/Update Domain DB logic
                # To ensure we have a domain_id, we need to insert the domain if it's new.
                # Since multiple threads might process same domain, we handle this carefully.
                # Actually, simplest is to just INSERT OR IGNORE / ON CONFLICT UPDATE for domain
                # every time we get a result. SQLite is fast enough for this.
                
                domain = result['domain']
                
                # Upsert Domain
                cursor.execute("""
                    INSERT INTO email_domains (domain, has_dns, has_mx, mx_records, checked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(domain) DO UPDATE SET
                    has_dns=excluded.has_dns,
                    has_mx=excluded.has_mx,
                    mx_records=excluded.mx_records,
                    checked_at=excluded.checked_at
                """, (domain, result['has_dns'], result['has_mx'], json.dumps(result['mx_records']), datetime.now()))
                
                # Get Domain ID (required for FK)
                # Since we just inserted/updated, we can select it.
                cursor.execute("SELECT id FROM email_domains WHERE domain = ?", (domain,))
                row = cursor.fetchone()
                domain_id = row['id'] if row else None
                
                # Insert Verification
                cursor.execute("""
                    INSERT INTO email_verifications 
                    (email, domain_id, format_valid, domain_valid, mx_valid, smtp_valid, final_status, checked_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    result['email'], 
                    domain_id, 
                    result['format_valid'], 
                    result['domain_valid'], 
                    result['mx_valid'], 
                    result['smtp_valid'], 
                    result['final_status'], 
                    datetime.now()
                ))

                count += 1
                if count % 100 == 0:
                    conn.commit()

            except Exception as e:
                logging.error(f"Error processing {email}: {e}")
    
    conn.commit()
    conn.close()
    print("Verification complete.")

if __name__ == "__main__":
    process_emails()
