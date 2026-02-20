
from db_manager import DBManager
from database import File, FileAnalysisLog, Article, Author

db = DBManager()
session = db.session

try:
    file_count = session.query(File).count()
    log_count = session.query(FileAnalysisLog).count()
    article_count = session.query(Article).count()
    author_count = session.query(Author).count()
    
    # Check for authors with emails
    authors_with_email = session.query(Author).filter(Author.email.isnot(None)).count()

    print(f"Files: {file_count}")
    print(f"Analysis Logs: {log_count}")
    print(f"Articles: {article_count}")
    print(f"Authors: {author_count}")
    print(f"Authors with Email: {authors_with_email}")

    # Check for files analyzed but no email for authors
    # This logic is a bit complex for a simple count, but let's try a sample
    
    analyzed_files = session.query(File).join(FileAnalysisLog).group_by(File.id).all()
    print(f"Files with at least one analysis log: {len(analyzed_files)}")

finally:
    db.close()
