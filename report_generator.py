import pandas as pd
from db_manager import DBManager
from database import CapturedEmail, Article, Edition, Journal
import datetime

def generate_reports():
    db = DBManager()
    session = db.session
    
    print("Generating reports...")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    
    # 1. Valid Emails Report
    # Join: CapturedEmail -> Article -> Edition -> Journal
    query = session.query(
        CapturedEmail.email,
        CapturedEmail.verification_status,
        CapturedEmail.valid_syntax,
        CapturedEmail.valid_domain,
        CapturedEmail.valid_mx,
        CapturedEmail.valid_smtp,
        Article.title.label('article_title'),
        Article.url.label('article_url'),
        Journal.name.label('journal_name')
    ).join(Article, CapturedEmail.article_id == Article.id)\
     .join(Edition, Article.edition_id == Edition.id)\
     .join(Journal, Edition.journal_id == Journal.id)
     
    df = pd.read_sql(query.statement, session.bind)
    
    # Valid Emails CSV
    valid_emails = df[df['verification_status'] == 'VALID']
    valid_csv = f"report_valid_emails_{timestamp}.csv"
    valid_emails.to_csv(valid_csv, index=False)
    print(f"Saved {len(valid_emails)} valid emails to {valid_csv}")
    
    # All Emails CSV
    all_csv = f"report_all_emails_{timestamp}.csv"
    df.to_csv(all_csv, index=False)
    print(f"Saved {len(df)} total emails to {all_csv}")
    
    # 2. Journal Stats
    # Group by journal
    stats = df.groupby('journal_name').agg({
        'email': 'count',
        'valid_smtp': lambda x: x.sum()
    }).rename(columns={'email': 'total_emails', 'valid_smtp': 'valid_emails'})
    
    stats_csv = f"report_journal_stats_{timestamp}.csv"
    stats.to_csv(stats_csv)
    print(f"Saved journal stats to {stats_csv}")
    
    db.close()

if __name__ == "__main__":
    generate_reports()
