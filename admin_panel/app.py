import sys
import os
from flask import Flask, render_template, request, redirect, url_for, flash, make_response, g, send_file
from sqlalchemy import func, case
import csv
import io

# Add parent directory to path to import database modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import get_session, Journal, Article, File, CapturedEmail, Author, Edition, ExecutionRun, ErrorLog

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Change this in production

def get_db():
    if 'db' not in g:
        g.db = get_session()
    return g.db

@app.teardown_appcontext
def shutdown_session(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

@app.route('/')
def dashboard():
    session = get_db()
    import datetime
    
    # helper for checking recent activity (10 mins)
    ten_mins_ago = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
    
    # --- Journals Stats ---
    total_journals = session.query(Journal).count()
    active_journals = session.query(Journal).filter(Journal.active == True).count()
    inactive_journals = total_journals - active_journals
    
    journals = session.query(Journal).order_by(Journal.name).all()
    journal_id = request.args.get('journal_id', type=int)

    # --- Editions Stats (Crawling Phase) ---
    if journal_id:
        total_editions = session.query(Edition).filter(Edition.journal_id == journal_id).count()
        completed_editions = session.query(Edition).filter(Edition.journal_id == journal_id, Edition.status.in_(['completed', 'completed_foreign'])).count()
        recent_completed_editions = session.query(Edition).filter(
            Edition.journal_id == journal_id,
            Edition.status.in_(['completed', 'completed_foreign']),
            Edition.updated_at >= ten_mins_ago
        ).count()
    else:
        total_editions = session.query(Edition).count()
        completed_editions = session.query(Edition).filter(Edition.status.in_(['completed', 'completed_foreign'])).count()
        recent_completed_editions = session.query(Edition).filter(
            Edition.status.in_(['completed', 'completed_foreign']),
            Edition.updated_at >= ten_mins_ago
        ).count()

    editions_pct = round((completed_editions / total_editions * 100) if total_editions > 0 else 0, 1)
    editions_speed = round(recent_completed_editions / 10.0, 1) # per min
    remaining_editions = total_editions - completed_editions
    editions_time_remaining_mins = round(remaining_editions / editions_speed) if editions_speed > 0 else -1

    # --- Articles Stats (Processing Phase) ---
    if journal_id:
        total_articles = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id).count()
        completed_articles = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id, Article.status.in_(['completed', 'completed_foreign', 'no_pdf'])).count()
        recent_files_created = session.query(File).join(Article).join(Edition).filter(
            Edition.journal_id == journal_id,
            File.created_at >= ten_mins_ago
        ).count()
    else:
        total_articles = session.query(Article).count()
        completed_articles = session.query(Article).filter(Article.status.in_(['completed', 'completed_foreign', 'no_pdf'])).count()
        recent_files_created = session.query(File).filter(
            File.created_at >= ten_mins_ago
        ).count()

    not_completed_articles = total_articles - completed_articles
    articles_pct = round((completed_articles / total_articles * 100) if total_articles > 0 else 0, 1)
    articles_speed = round(recent_files_created / 10.0, 1) # per min
    remaining_articles_to_process = total_articles - completed_articles
    articles_time_remaining_mins = round(remaining_articles_to_process / articles_speed) if articles_speed > 0 else -1

    # --- Emails Stats (Verification Phase) ---
    if journal_id:
        total_emails = session.query(func.count(func.distinct(CapturedEmail.email)))\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(Edition.journal_id == journal_id).scalar() or 0
        valid_emails = session.query(func.count(func.distinct(CapturedEmail.email)))\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(
                Edition.journal_id == journal_id,
                CapturedEmail.verification_status == 'VALID'
            ).scalar() or 0
        invalid_emails = session.query(func.count(func.distinct(CapturedEmail.email)))\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(
                Edition.journal_id == journal_id,
                CapturedEmail.verification_status == 'INVALID'
            ).scalar() or 0
        recent_verified_emails = session.query(func.count(func.distinct(CapturedEmail.email)))\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(
                Edition.journal_id == journal_id,
                CapturedEmail.verification_status.in_(['VALID', 'INVALID']),
                CapturedEmail.updated_at >= ten_mins_ago
            ).scalar() or 0
    else:
        total_emails = session.query(func.count(func.distinct(CapturedEmail.email))).scalar() or 0
        valid_emails = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'VALID').scalar() or 0
        invalid_emails = session.query(func.count(func.distinct(CapturedEmail.email))).filter(CapturedEmail.verification_status == 'INVALID').scalar() or 0
        recent_verified_emails = session.query(func.count(func.distinct(CapturedEmail.email))).filter(
            CapturedEmail.verification_status.in_(['VALID', 'INVALID']),
            CapturedEmail.updated_at >= ten_mins_ago
        ).scalar() or 0

    verified_emails = min(valid_emails + invalid_emails, total_emails)
    emails_pct = round((verified_emails / total_emails * 100) if total_emails > 0 else 0, 1)
    emails_speed = round(recent_verified_emails / 10.0, 1)
    remaining_emails_to_verify = max(0, total_emails - verified_emails)
    emails_time_remaining_mins = round(remaining_emails_to_verify / emails_speed) if emails_speed > 0 else -1
    
    # Helper to format time
    def format_time(mins):
        if mins < 0: return "Unknown"
        if mins == 0: return "Done"
        h = max(0, mins // 60)
        m = max(0, mins % 60)
        return f"{h}h {m}m" if h > 0 else f"{m}m"

    return render_template('dashboard.html', 
                           total_journals=total_journals, active_journals=active_journals, inactive_journals=inactive_journals,
                           journals=journals, selected_journal_id=journal_id,
                           total_editions=total_editions, completed_editions=completed_editions, 
                           editions_pct=editions_pct, editions_speed=editions_speed,
                           editions_time_remaining=format_time(editions_time_remaining_mins),
                           
                           total_articles=total_articles, completed_articles=completed_articles, not_completed_articles=not_completed_articles,
                           articles_pct=articles_pct, articles_speed=articles_speed,
                           articles_time_remaining=format_time(articles_time_remaining_mins),
                           
                           total_emails=total_emails, valid_emails=valid_emails, invalid_emails=invalid_emails,
                           emails_pct=emails_pct, emails_speed=emails_speed,
                           emails_time_remaining=format_time(emails_time_remaining_mins))

@app.route('/files/download/<int:id>')
def download_file(id):
    session = get_db()
    file_record = session.query(File).get(id)
    if not file_record or not file_record.local_path:
        return "File not found", 404
    
    if os.path.isabs(file_record.local_path):
        abs_path = file_record.local_path
    else:
        abs_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', file_record.local_path))
        
    if not os.path.exists(abs_path):
        return "File not found on server", 404
        
    return send_file(abs_path, as_attachment=True)

@app.route('/journals')
def list_journals():
    page = request.args.get('page', 1, type=int)
    per_page = 200
    session = get_db()
    
    # Total unfiltered
    total_records = session.query(Journal).count()
    
    # Filters
    f_name = request.args.get('name')
    f_source = request.args.get('source')
    f_status = request.args.get('status') 
    f_qualis = request.args.get('qualis')
    
    query = session.query(Journal)
    
    if f_name:
        query = query.filter(Journal.name.like(f"%{f_name}%"))
    if f_source:
        query = query.filter(Journal.source_type == f_source)
    if f_status:
        is_active = True if f_status == 'active' else False
        query = query.filter(Journal.active == is_active)
    if f_qualis:
        if f_qualis.upper() == 'NONE':
            query = query.filter((Journal.qualis == '') | (Journal.qualis == None))
        else:
            query = query.filter(Journal.qualis == f_qualis)
        
    # Check for export
    export = request.args.get('export')
    
    if export == 'csv':
        # Export all matching (without pagination)
        all_journals = query.order_by(Journal.name).all()
        
        import io
        import csv
        from flask import make_response
        si = io.StringIO()
        si.write('\ufeff')
        cw = csv.writer(si)
        cw.writerow(['issn', 'title', 'qualis', 'area'])
        for j in all_journals:
            # Resolve ISSN
            issn_candidates = []
            for val in [j.issn_electronic, j.issn_print, j.issn]:
                if val and str(val).strip():
                    cleaned = str(val).replace('ISSN:', '').replace('issn:', '').strip()
                    if cleaned and cleaned.lower() not in ['none', 'nan', 'null', ''] and cleaned not in issn_candidates:
                        issn_candidates.append(cleaned)
            issn_val = ', '.join(issn_candidates) if issn_candidates else ''
            title_val = (j.name or '').strip()
            qualis_val = (j.qualis or '').strip()
            if qualis_val.lower() in ['none', 'nan']:
                qualis_val = ''
            area_val = (j.subject_area or '').strip()
            if area_val.lower() in ['none', 'nan']:
                area_val = ''
            cw.writerow([issn_val, title_val, qualis_val, area_val])
        
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=revistas.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output
        
    filtered_records = query.count()
    journals = query.order_by(Journal.name).limit(per_page).offset((page - 1) * per_page).all()
    
    # Calculate emails amount
    if journals:
        from sqlalchemy import func
        from database import Edition, Article, CapturedEmail
        journal_ids = [j.id for j in journals]
        counts = session.query(
            Journal.id,
            func.count(func.distinct(CapturedEmail.email))
        ).outerjoin(Edition, Edition.journal_id == Journal.id)\
         .outerjoin(Article, Article.edition_id == Edition.id)\
         .outerjoin(CapturedEmail, CapturedEmail.article_id == Article.id)\
         .filter(Journal.id.in_(journal_ids))\
         .group_by(Journal.id).all()
         
        count_dict = dict(counts)
        for j in journals:
            j.email_count = count_dict.get(j.id, 0)
    else:
        for j in journals:
            j.email_count = 0
    
    return render_template('list_journals.html', journals=journals, page=page, total=filtered_records, per_page=per_page,
                           total_records=total_records, filtered_records=filtered_records,
                           f_name=f_name, f_source=f_source, f_status=f_status, f_qualis=f_qualis)

@app.route('/journals/create', methods=['GET', 'POST'])
def create_journal():
    if request.method == 'POST':
        session = get_db()
        new_journal = Journal(
            name=request.form['name'],
            url=request.form['url'],
            acronym=request.form.get('acronym'),
            issn=request.form.get('issn'),
            source_type=request.form['source_type'],
            active='active' in request.form,
            # New Fields
            address=request.form.get('address'),
            publisher_name=request.form.get('publisher_name'),
            publisher_loc=request.form.get('publisher_loc'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            issn_print=request.form.get('issn_print'),
            issn_electronic=request.form.get('issn_electronic'),
            qualis=request.form.get('qualis'),
            subject_area=request.form.get('subject_area')
        )
        session.add(new_journal)
        session.commit()
        return redirect(url_for('list_journals'))
    return render_template('form_journal.html', journal=None)

@app.route('/journals/edit/<int:id>', methods=['GET', 'POST'])
def edit_journal(id):
    session = get_db()
    journal = session.query(Journal).get(id)
    if not journal:
        return "Journal not found", 404
        
    if request.method == 'POST':
        journal.name = request.form['name']
        journal.url = request.form['url']
        journal.acronym = request.form.get('acronym')
        journal.issn = request.form.get('issn')
        journal.source_type = request.form['source_type']
        journal.active = 'active' in request.form
        
        # New Fields
        journal.address = request.form.get('address')
        journal.publisher_name = request.form.get('publisher_name')
        journal.publisher_loc = request.form.get('publisher_loc')
        journal.email = request.form.get('email')
        journal.phone = request.form.get('phone')
        journal.issn_print = request.form.get('issn_print')
        journal.issn_electronic = request.form.get('issn_electronic')
        journal.qualis = request.form.get('qualis')
        journal.subject_area = request.form.get('subject_area')
        
        session.commit()
        return redirect(url_for('list_journals'))
    
    # Get articles for this journal
    articles = session.query(Article).join(Edition).filter(Edition.journal_id == id).limit(50).all()
    
    return render_template('form_journal.html', journal=journal, articles=articles)

@app.route('/journals/delete/<int:id>')
def delete_journal(id):
    session = get_db()
    journal = session.query(Journal).get(id)
    if journal:
        session.delete(journal)
        session.commit()
    return redirect(url_for('list_journals'))

# --- ARTICLES ---
@app.route('/articles')
def list_articles():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    session = get_db()
    
    # Total unfiltered
    total_records = session.query(Article).count()
    
    # Filters
    f_title = request.args.get('title')
    f_status = request.args.get('status')
    
    query = session.query(Article)
    
    if f_title:
        query = query.filter(Article.title.like(f"%{f_title}%"))
    if f_status:
        query = query.filter(Article.status == f_status)
        
    filtered_records = query.count()
    articles = query.order_by(Article.id.desc()).limit(per_page).offset((page - 1) * per_page).all()
    
    return render_template('list_articles.html', articles=articles, page=page, total=filtered_records, per_page=per_page,
                           total_records=total_records, filtered_records=filtered_records,
                           f_title=f_title, f_status=f_status)

@app.route('/articles/edit/<int:id>', methods=['GET', 'POST'])
def edit_article(id):
    session = get_db()
    article = session.query(Article).get(id)
    if not article:
        return "Article not found", 404
        
    if request.method == 'POST':
        article.title = request.form['title']
        article.url = request.form['url']
        article.status = request.form['status']
        
        # New Fields
        article.doi = request.form.get('doi')
        article.abstract = request.form.get('abstract')
        article.abstract_en = request.form.get('abstract_en')
        article.page_numbers = request.form.get('page_numbers')
        article.license_url = request.form.get('license_url')
        article.copyright_holder = request.form.get('copyright_holder')
        article.language = request.form.get('language')
        
        import datetime
        
        # Helper to parse form dates
        def parse_form_date(d_str):
            if not d_str: return None
            try:
                # Handle standard SQL str output 'YYYY-MM-DD HH:MM:SS' or just 'YYYY-MM-DD'
                return datetime.datetime.fromisoformat(str(d_str).replace(' ', 'T'))
            except:
                try: 
                     return datetime.datetime.strptime(d_str, '%Y-%m-%d')
                except:
                     return None
        
        article.publication_date = parse_form_date(request.form.get('publication_date'))
        article.submission_date = parse_form_date(request.form.get('submission_date'))
        article.acceptance_date = parse_form_date(request.form.get('acceptance_date'))
        
        session.commit()
        return redirect(url_for('list_articles'))
    
    # Get files and emails
    files = session.query(File).filter(File.article_id == id).all()
    emails = session.query(CapturedEmail).filter(CapturedEmail.article_id == id).all()
    
    return render_template('form_article.html', article=article, files=files, emails=emails)

@app.route('/articles/delete/<int:id>')
def delete_article(id):
    session = get_db()
    article = session.query(Article).get(id)
    if article:
        session.delete(article)
        session.commit()
    return redirect(url_for('list_articles'))

# --- FILES ---
@app.route('/files')
def list_files():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    session = get_db()
    
    # Total unfiltered
    total_records = session.query(File).count()
    
    # Filters
    f_type = request.args.get('type')
    f_path = request.args.get('path')
    
    query = session.query(File)
    
    if f_type:
        query = query.filter(File.file_type == f_type)
    if f_path:
        query = query.filter(File.local_path.like(f"%{f_path}%"))
        
    filtered_records = query.count()
    files = query.order_by(File.id.desc()).limit(per_page).offset((page - 1) * per_page).all()
    
    return render_template('list_files.html', files=files, page=page, total=filtered_records, per_page=per_page,
                           total_records=total_records, filtered_records=filtered_records,
                           f_type=f_type, f_path=f_path)

@app.route('/files/edit/<int:id>', methods=['GET', 'POST'])
def edit_file(id):
    session = get_db()
    file_record = session.query(File).get(id)
    if not file_record:
        return "File not found", 404
        
    if request.method == 'POST':
        file_record.file_type = request.form['file_type']
        file_record.local_path = request.form['local_path']
        file_record.url = request.form['url']
        session.commit()
        return redirect(url_for('list_files'))
    
    emails = []
    if file_record.article_id:
        emails = session.query(CapturedEmail).filter(CapturedEmail.article_id == file_record.article_id).all()
        
    return render_template('form_file.html', file=file_record, emails=emails)

@app.route('/files/delete/<int:id>')
def delete_file(id):
    session = get_db()
    file_record = session.query(File).get(id)
    if file_record:
        session.delete(file_record)
        session.commit()
    return redirect(url_for('list_files'))

# --- EMAILS ---
@app.route('/emails')
def list_emails():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    session = get_db()
    
    # Total unfiltered
    total_records = session.query(CapturedEmail).count()
    
    # Filters
    f_email = request.args.get('email')
    f_status = request.args.get('status')
    
    query = session.query(CapturedEmail)
    
    if f_email:
        query = query.filter(CapturedEmail.email.like(f"%{f_email}%"))
    if f_status:
        query = query.filter(CapturedEmail.verification_status == f_status)
        
    filtered_records = query.count()
    emails = query.order_by(CapturedEmail.id.desc()).limit(per_page).offset((page - 1) * per_page).all()
    
    return render_template('list_emails.html', emails=emails, page=page, total=filtered_records, per_page=per_page,
                           total_records=total_records, filtered_records=filtered_records,
                           f_email=f_email, f_status=f_status)

@app.route('/emails/edit/<int:id>', methods=['GET', 'POST'])
def edit_email(id):
    session = get_db()
    email_record = session.query(CapturedEmail).get(id)
    if not email_record:
        return "Email not found", 404
        
    if request.method == 'POST':
        email_record.email = request.form['email']
        email_record.verification_status = request.form['verification_status']
        session.commit()
        return redirect(url_for('list_emails'))
        
    return render_template('form_email.html', email=email_record)

@app.route('/emails/delete/<int:id>')
def delete_email(id):
    session = get_db()
    email_record = session.query(CapturedEmail).get(id)
    if email_record:
        session.delete(email_record)
        session.commit()
    return redirect(url_for('list_emails'))

# --- REPORTS ---

@app.route('/reports/emails_by_journal')
def report_emails_by_journal():
    session = get_db()
    journals = session.query(Journal).order_by(Journal.name).all()
    
    journal_id = request.args.get('journal_id', type=int)
    status_filter = request.args.get('status')
    export = request.args.get('export')
    
    emails = []
    selected_journal = None
    
    if journal_id:
        selected_journal = session.query(Journal).get(journal_id)
        query = session.query(CapturedEmail)\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(Edition.journal_id == journal_id)
        
        if status_filter:
            query = query.filter(CapturedEmail.verification_status == status_filter)
            
        query = query.group_by(CapturedEmail.email).order_by(CapturedEmail.email.asc())
        emails = query.all()
        
        if export == 'csv':
            si = io.StringIO()
            cw = csv.writer(si)
            cw.writerow(['ID', 'Email', 'Status', 'Article ID', 'Article Title'])
            for email in emails:
                art_id = email.article.id if email.article else ''
                art_title = email.article.title if email.article else ''
                cw.writerow([email.id, email.email, email.verification_status, art_id, art_title])
            
            output = make_response(si.getvalue())
            output.headers["Content-Disposition"] = f"attachment; filename=emails_journal_{journal_id}.csv"
            output.headers["Content-type"] = "text/csv"
            return output

    return render_template('report_emails_journal.html', journals=journals, emails=emails, selected_journal_id=journal_id, selected_status=status_filter)

@app.route('/reports/articles_by_journal')
def report_articles_by_journal():
    session = get_db()
    journals = session.query(Journal).order_by(Journal.name).all()
    
    journal_id = request.args.get('journal_id', type=int)
    export = request.args.get('export')
    
    articles = []
    
    if journal_id:
        query = session.query(Article).join(Edition).filter(Edition.journal_id == journal_id)
        articles = query.all()
        
        if export == 'csv':
            si = io.StringIO()
            cw = csv.writer(si)
            cw.writerow(['ID', 'Title', 'Status', 'Date', 'URL'])
            for art in articles:
                cw.writerow([art.id, art.title, art.status, art.created_at, art.url])
            
            output = make_response(si.getvalue())
            output.headers["Content-Disposition"] = f"attachment; filename=articles_journal_{journal_id}.csv"
            output.headers["Content-type"] = "text/csv"
            return output

    return render_template('report_articles_journal.html', journals=journals, articles=articles, selected_journal_id=journal_id)

@app.route('/reports/emails_multi_journal')
def report_emails_multi_journal():
    session = get_db()
    journals = session.query(Journal).order_by(Journal.name).all()
    
    counts = session.query(
        Journal.id,
        func.count(func.distinct(CapturedEmail.email))
    ).outerjoin(Edition, Edition.journal_id == Journal.id)\
     .outerjoin(Article, Article.edition_id == Edition.id)\
     .outerjoin(CapturedEmail, CapturedEmail.article_id == Article.id)\
     .group_by(Journal.id).all()
     
    count_dict = dict(counts)
    for j in journals:
        j.email_count = count_dict.get(j.id, 0)
    
    # In a GET request form, multiple checkboxes with the same name will be a list
    journal_ids = request.args.getlist('journal_ids', type=int)
    status_filter = request.args.get('status')
    export = request.args.get('export')
    
    emails = []
    
    if journal_ids:
        query = session.query(CapturedEmail)\
            .join(Article, CapturedEmail.article_id == Article.id)\
            .join(Edition, Article.edition_id == Edition.id)\
            .filter(Edition.journal_id.in_(journal_ids))
        
        if status_filter:
            query = query.filter(CapturedEmail.verification_status == status_filter)
            
        query = query.group_by(CapturedEmail.email).order_by(CapturedEmail.email.asc())
        
        if export == 'csv':
            emails = query.all()
            si = io.StringIO()
            cw = csv.writer(si)
            cw.writerow(['ID do Periódico', 'Nome do Periódico', 'ID', 'Email', 'Status', 'Article ID', 'Article Title'])
            for email in emails:
                j_id = email.article.edition.journal.id if (email.article and email.article.edition and email.article.edition.journal) else ''
                j_name = email.article.edition.journal.name if (email.article and email.article.edition and email.article.edition.journal) else ''
                art_id = email.article.id if email.article else ''
                art_title = email.article.title if email.article else ''
                cw.writerow([j_id, j_name, email.id, email.email, email.verification_status, art_id, art_title])
            
            output = make_response(si.getvalue())
            output.headers["Content-Disposition"] = "attachment; filename=emails_multi_journal.csv"
            output.headers["Content-type"] = "text/csv"
            return output
            
        emails = query.limit(1000).all()

    return render_template('report_emails_multi_journal.html', 
                           journals=journals, 
                           emails=emails, 
                           selected_journal_ids=journal_ids, 
                           selected_status=status_filter)


@app.route('/reports/emails_general')
def report_emails_general():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    session = get_db()
    journals = session.query(Journal).order_by(Journal.name).all()
    
    # Filters
    journal_id = request.args.get('journal_id', type=int)
    domain = request.args.get('domain')
    email_like = request.args.get('email_like')
    status = request.args.get('status')
    export = request.args.get('export')
    
    query = session.query(CapturedEmail)\
        .join(Article, CapturedEmail.article_id == Article.id)\
        .join(Edition, Article.edition_id == Edition.id)\
        .join(Journal, Edition.journal_id == Journal.id)
    
    if journal_id:
        query = query.filter(Journal.id == journal_id)
    if domain:
        query = query.filter(CapturedEmail.email.like(f"%@{domain}%"))
    if email_like:
        query = query.filter(CapturedEmail.email.like(f"%{email_like}%"))
    if status:
        query = query.filter(CapturedEmail.verification_status == status)
        
    query = query.group_by(CapturedEmail.email)
        
    if export == 'csv':
        # Export all matching
        emails = query.order_by(CapturedEmail.email.asc()).all()
        si = io.StringIO()
        cw = csv.writer(si)
        cw.writerow(['ID', 'Email', 'Status', 'Journal', 'Article'])
        for email in emails:
            j_name = email.article.edition.journal.name if (email.article and email.article.edition and email.article.edition.journal) else ''
            art_title = email.article.title if email.article else ''
            cw.writerow([email.id, email.email, email.verification_status, j_name, art_title])
        
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=emails_general.csv"
        output.headers["Content-type"] = "text/csv"
        return output

    # Pagination for view
    total = query.count()
    emails = query.order_by(CapturedEmail.id.desc()).limit(per_page).offset((page - 1) * per_page).all()
    
    return render_template('report_emails_general.html', 
                           emails=emails, journals=journals, 
                           page=page, total=total, per_page=per_page,
                           # Pass filters back to template
                           f_journal_id=journal_id, f_domain=domain, f_email_like=email_like, f_status=status)

# --- TELEMETRY & RUNS ---

@app.route('/runs')
def list_runs_view():
    session = get_db()
    runs = session.query(ExecutionRun).order_by(ExecutionRun.start_time.desc()).limit(50).all()
    
    total_runs = session.query(ExecutionRun).count()
    completed_runs = session.query(ExecutionRun).filter(ExecutionRun.status == 'completed').count()
    crashed_runs = session.query(ExecutionRun).filter(ExecutionRun.status == 'crashed').count()
    total_recovered = session.query(func.sum(ExecutionRun.crash_recovered_tasks)).scalar() or 0
    
    recent_errors = session.query(ErrorLog).order_by(ErrorLog.created_at.desc()).limit(20).all()
    
    return render_template(
        'list_runs.html',
        runs=runs,
        total_runs=total_runs,
        completed_runs=completed_runs,
        crashed_runs=crashed_runs,
        total_recovered=total_recovered,
        recent_errors=recent_errors
    )

# --- HIERARCHICAL TREE EXPLORER (Revista -> Edição -> Artigo -> E-mails) ---

@app.route('/explorer')
def explorer_view():
    from urllib.parse import urlparse
    from collections import defaultdict
    session = get_db()
    journals = session.query(Journal).order_by(Journal.name).all()
    journal_id = request.args.get('journal_id', type=int)
    
    if not journal_id and journals:
        j129 = next((j for j in journals if j.id == 129), None)
        journal_id = j129.id if j129 else journals[0].id
        
    selected_journal = session.query(Journal).get(journal_id) if journal_id else None
    
    # Default to legitimate for focused clean view
    status_filter = request.args.get('status', 'legitimate')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 100
    
    tree_data = None
    stats = None
    
    if selected_journal:
        base_host = urlparse(selected_journal.url).netloc.lower() if selected_journal.url else ''
        
        # 1. Fast Batch KPI Stats
        total_editions = session.query(Edition).filter(Edition.journal_id == selected_journal.id).count()
        completed_editions = session.query(Edition).filter(Edition.journal_id == selected_journal.id, Edition.status.in_(['completed', 'completed_foreign'])).count()
        pending_editions = max(0, total_editions - completed_editions)
        
        # Top KPIs - Canonical editions vs Aliases
        canon_eds_subq = session.query(Edition.id).filter(
            Edition.journal_id == selected_journal.id,
            (Edition.is_canonical == True) | (Edition.is_canonical.is_(None))
        )
        total_editions = canon_eds_subq.count()
        total_aliases = session.query(Edition).filter(
            Edition.journal_id == selected_journal.id,
            Edition.is_canonical == False
        ).count()
        
        completed_editions = session.query(Edition).filter(
            Edition.id.in_(canon_eds_subq),
            Edition.status.in_(['completed', 'completed_foreign'])
        ).count()
        pending_editions = max(0, total_editions - completed_editions)
        
        # Article subquery
        art_subq = session.query(Article.id).join(Edition).filter(Edition.journal_id == selected_journal.id)
        
        total_articles = session.query(Article).filter(Article.id.in_(art_subq)).count()
        completed_articles = session.query(Article).filter(Article.id.in_(art_subq), Article.status.in_(['completed', 'completed_foreign'])).count()
        no_pdf_articles = session.query(Article).filter(Article.id.in_(art_subq), Article.status == 'no_pdf').count()
        error_articles = session.query(Article).filter(Article.id.in_(art_subq), Article.status.like('%error%')).count()
        pending_articles = max(0, total_articles - (completed_articles + no_pdf_articles + error_articles))
        
        # Email stats
        email_counts = session.query(
            CapturedEmail.verification_status,
            func.count(func.distinct(CapturedEmail.email))
        ).filter(CapturedEmail.article_id.in_(art_subq)).group_by(CapturedEmail.verification_status).all()
        
        email_map = dict(email_counts)
        valid_emails = email_map.get('VALID', 0)
        invalid_emails = email_map.get('INVALID', 0)
        pending_emails = email_map.get('PENDING', 0) + email_map.get('PROCESSING', 0)
        total_emails = valid_emails + invalid_emails + pending_emails
        
        stats = {
            'total_editions': total_editions,
            'total_aliases': total_aliases,
            'completed_editions': completed_editions,
            'pending_editions': pending_editions,
            'editions_pct': round((completed_editions / total_editions * 100) if total_editions > 0 else 0, 1),
            
            'total_articles': total_articles,
            'completed_articles': completed_articles,
            'no_pdf_articles': no_pdf_articles,
            'error_articles': error_articles,
            'pending_articles': pending_articles,
            'articles_pct': round(((completed_articles + no_pdf_articles) / total_articles * 100) if total_articles > 0 else 0, 1),
            
            'total_emails': total_emails,
            'valid_emails': valid_emails,
            'invalid_emails': invalid_emails,
            'pending_emails': pending_emails,
            'emails_pct': round((valid_emails / total_emails * 100) if total_emails > 0 else 0, 1)
        }
        
        # 2. Paginated Editions Query
        show_aliases = request.args.get('show_aliases', '0') == '1'
        with_articles = request.args.get('with_articles', '1')
        
        ed_query = session.query(Edition).filter(Edition.journal_id == selected_journal.id)
        
        if not show_aliases:
            # Show only canonical editions by default
            ed_query = ed_query.filter((Edition.is_canonical == True) | (Edition.is_canonical.is_(None)))
            
        if with_articles == '1':
            # Show editions that actually contain articles
            has_art_subq = session.query(Article.edition_id).distinct()
            ed_query = ed_query.filter(Edition.id.in_(has_art_subq))
            
        if status_filter == 'legitimate':
            ed_query = ed_query.filter(
                Edition.url.like(f'%{base_host}%'),
                (Edition.url.like('%/issue/view/%') | Edition.url.like('%/toc%') | Edition.url.like('%/grid%'))
            )
        elif status_filter == 'pending':
            ed_query = ed_query.filter(Edition.status.in_(['found', 'processing']))
        elif status_filter == 'completed':
            ed_query = ed_query.filter(Edition.status.in_(['completed', 'completed_foreign']))
            
        if search_query:
            # Find editions that match, OR contain articles matching title/url, OR contain emails matching, OR have aliases matching
            matched_ed_by_art = session.query(Article.edition_id).filter(
                (Article.title.ilike(f'%{search_query}%')) |
                (Article.url.ilike(f'%{search_query}%'))
            )
            matched_ed_by_email = session.query(Article.edition_id).join(CapturedEmail).filter(
                CapturedEmail.email.ilike(f'%{search_query}%')
            )
            matched_ed_by_alias = session.query(Edition.canonical_edition_id).filter(
                (Edition.title.ilike(f'%{search_query}%')) |
                (Edition.url.ilike(f'%{search_query}%')) |
                (Edition.alias_notes.ilike(f'%{search_query}%'))
            )
            ed_query = ed_query.filter(
                (Edition.title.ilike(f'%{search_query}%')) |
                (Edition.url.ilike(f'%{search_query}%')) |
                (Edition.id.in_(matched_ed_by_art)) |
                (Edition.id.in_(matched_ed_by_email)) |
                (Edition.id.in_(matched_ed_by_alias))
            )
            
        total_ed_filtered = ed_query.count()
        editions = ed_query.order_by(Edition.id.desc()).limit(per_page).offset((page - 1) * per_page).all()
        
        # 3. Bulk Fetch in 3 Queries (Fastest execution)
        edition_ids = [e.id for e in editions]
        
        if edition_ids:
            all_articles = session.query(Article).filter(Article.edition_id.in_(edition_ids)).order_by(Article.id.asc()).all()
            article_ids = [a.id for a in all_articles]
            
            # Map articles by edition_id
            articles_by_edition = defaultdict(list)
            for a in all_articles:
                articles_by_edition[a.edition_id].append(a)
                
            # Fetch emails & files in bulk
            emails_by_article = defaultdict(list)
            if article_ids:
                all_emails = session.query(CapturedEmail).filter(CapturedEmail.article_id.in_(article_ids)).order_by(CapturedEmail.id.asc()).all()
                for em in all_emails:
                    emails_by_article[em.article_id].append(em)
                    
            files_by_article = defaultdict(list)
            if article_ids:
                all_files = session.query(File).filter(File.article_id.in_(article_ids)).all()
                for f in all_files:
                    files_by_article[f.article_id].append(f)
                    
            # Fetch aliases for canonical editions
            aliases_by_canon = defaultdict(list)
            all_aliases = session.query(Edition).filter(Edition.canonical_edition_id.in_(edition_ids)).all()
            for al in all_aliases:
                aliases_by_canon[al.canonical_edition_id].append(al)
                    
            tree_editions = []
            for ed in editions:
                ed_arts = []
                for art in articles_by_edition.get(ed.id, []):
                    art_emails = emails_by_article.get(art.id, [])
                    art_files = files_by_article.get(art.id, [])
                    ed_arts.append({
                        'article': art,
                        'emails': art_emails,
                        'files': art_files,
                        'email_count': len(art_emails),
                        'valid_email_count': sum(1 for e in art_emails if e.verification_status == 'VALID')
                    })
                    
                ed_host = urlparse(ed.url).netloc.lower() if ed.url else ''
                is_foreign = bool(base_host and ed_host and (ed_host != base_host))
                ed_aliases = aliases_by_canon.get(ed.id, [])
                
                tree_editions.append({
                    'edition': ed,
                    'domain': ed_host,
                    'is_foreign': is_foreign,
                    'aliases': ed_aliases,
                    'alias_count': len(ed_aliases),
                    'articles': ed_arts,
                    'article_count': len(ed_arts),
                    'completed_count': sum(1 for a in ed_arts if a['article'].status in ['completed', 'completed_foreign', 'no_pdf']),
                    'total_emails': sum(a['email_count'] for a in ed_arts),
                    'valid_emails': sum(a['valid_email_count'] for a in ed_arts)
                })
        else:
            tree_editions = []
            
        tree_data = {
            'editions': tree_editions,
            'total_editions_filtered': total_ed_filtered,
            'page': page,
            'per_page': per_page,
            'total_pages': (total_ed_filtered + per_page - 1) // per_page if total_ed_filtered > 0 else 1
        }
        
    return render_template(
        'explorer.html',
        journals=journals,
        selected_journal=selected_journal,
        selected_journal_id=journal_id,
        stats=stats,
        tree_data=tree_data,
        status_filter=status_filter,
        with_articles=with_articles,
        show_aliases=show_aliases,
        search_query=search_query
    )

if __name__ == '__main__':
    app.run(debug=True, port=5000)



