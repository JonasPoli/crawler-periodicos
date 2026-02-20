import time
import sys
import os
import uuid
import re
import socket
import smtplib
import dns.resolver
import datetime
from db_manager import DBManager
from database import CapturedEmail

# Regex for basic syntax
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def log(worker_id, message):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [Verifier {worker_id}] {message}")

def verify_syntax(email):
    return bool(EMAIL_REGEX.match(email))

def verify_domain_dns(domain):
    try:
        dns.resolver.resolve(domain, 'MX')
        return True
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
        try:
            dns.resolver.resolve(domain, 'A')
            return True
        except:
            return False
    except:
        return False

def get_mx_record(domain):
    try:
        records = dns.resolver.resolve(domain, 'MX')
        mx_record = str(records[0].exchange)
        return mx_record
    except:
        return None

def verify_smtp(email, mx_record):
    if not mx_record:
        return False
    
    try:
        server = smtplib.SMTP(timeout=5)
        server.set_debuglevel(0)
        
        # Connect
        code, message = server.connect(mx_record)
        if code != 220:
            server.quit()
            return False
        
        server.helo(socket.gethostname())
        server.mail('test@example.com')
        code, message = server.rcpt(email)
        server.quit()
        
        if code == 250:
            return True
        return False
        
    except Exception as e:
        return False

def run_verifier_worker(worker_id, stop_event=None):
    log(worker_id, "Started.")
    
    db_manager = DBManager()
    
    empty_cycles = 0
    
    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            email_record = db_manager.get_next_email_for_verification(worker_id)
            
            if not email_record:
                empty_cycles += 1
                if empty_cycles > 300: 
                     log(worker_id, "Idle. Exiting.")
                     break
                time.sleep(2)
                continue
            
            empty_cycles = 0
            
            email_addr = email_record.email
            domain = email_addr.split('@')[-1]
            status_detail = "UNKNOWN"
            
            try:
                start_time = time.time()
                # 1. Syntax
                valid_syntax = verify_syntax(email_addr)
                email_record.valid_syntax = valid_syntax
                
                if not valid_syntax:
                    email_record.verification_status = 'INVALID'
                    status_detail = "SYNTAX_ERROR"
                    email_record.valid_domain = False
                    email_record.valid_mx = False
                    email_record.valid_smtp = False
                else:
                    # 2. Domain & MX
                    mx_record = get_mx_record(domain)
                    
                    email_record.valid_domain = True 
                    if not mx_record:
                        if verify_domain_dns(domain):
                            email_record.valid_domain = True
                            email_record.valid_mx = False
                            status_detail = "NO_MX_RECORD"
                        else:
                            email_record.valid_domain = False
                            email_record.valid_mx = False
                            email_record.verification_status = 'INVALID'
                            status_detail = "DOMAIN_INVALID"
                    else:
                        email_record.valid_domain = True
                        email_record.valid_mx = True
                    
                        # 3. SMTP
                        is_valid_smtp = verify_smtp(email_addr, mx_record)
                        email_record.valid_smtp = is_valid_smtp
                        
                        if is_valid_smtp:
                            email_record.verification_status = 'VALID'
                            status_detail = "VALID_SMTP"
                        else:
                            email_record.verification_status = 'INVALID'
                            status_detail = "SMTP_REJECTED"

                duration = time.time() - start_time
                log(worker_id, f"VERIFIED: {email_addr} -> {email_record.verification_status} ({status_detail}) ({duration:.2f}s)")

                # Clean up
                email_record.worker_id = None
                email_record.lock_time = None
                db_manager.session.commit()
            
            except Exception as e:
                log(worker_id, f"ERROR verifying {email_addr}: {e}")
                db_manager.session.rollback()

    except KeyboardInterrupt:
        log(worker_id, "Stopping...")
    finally:
        db_manager.close()

if __name__ == "__main__":
    run_verifier_worker(str(uuid.uuid4()))
