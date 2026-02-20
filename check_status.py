import os
import sys
from datetime import datetime
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from database import Journal, Edition, Article, CapturedEmail, DATABASE_URL

def get_session():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    return Session()

def print_section(title):
    print(f"\n{'='*40}")
    print(f" {title}")
    print(f"{'='*40}")

def main():
    session = get_session()
    
    try:
        # 1. Journals Stats
        total_journals = session.query(Journal).count()
        active_journals = session.query(Journal).filter_by(active=True).count()
        
        # 2. Editions Stats
        total_editions = session.query(Edition).count()
        completed_editions = session.query(Edition).filter_by(status='completed').count()
        found_editions = session.query(Edition).filter_by(status='found').count()
        processing_editions = session.query(Edition).filter_by(status='processing').count()
        
        # 3. Articles Stats
        total_articles = session.query(Article).count()
        
        article_status_counts = session.query(Article.status, func.count(Article.status)).group_by(Article.status).all()
        article_stats = {status: count for status, count in article_status_counts}
        
        # 3.5 Authors Stats
        from database import Author
        total_authors = session.query(Author).count()
        
        # 4. Email Stats
        total_emails = session.query(CapturedEmail).count()
        email_status_counts = session.query(CapturedEmail.verification_status, func.count(CapturedEmail.verification_status)).group_by(CapturedEmail.verification_status).all()
        email_stats = {status: count for status, count in email_status_counts}
        
        valid_emails = email_stats.get('VALID', 0)
        pending_emails = email_stats.get('PENDING', 0)
        processing_emails = email_stats.get('PROCESSING', 0)
        invalid_emails = email_stats.get('INVALID', 0)
        
        # --- REPORT ---
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        print_section(f"RELATÓRIO DE STATUS DO PROJETO - {now}")
        
        print(f"PERIÓDICOS (JOURNALS):")
        print(f"  Total:  {total_journals}")
        print(f"  Ativos: {active_journals}")
        
        print_section("PROGRESSO DO CRAWLER (Edições)")
        print(f"  Total de Edições Descobertas: {total_editions}")
        print(f"  Concluídas: {completed_editions} ({(completed_editions/total_editions*100) if total_editions else 0:.1f}%)")
        print(f"  Pendentes:  {found_editions}")
        print(f"  Em Processamento: {processing_editions}")
        
        print_section("PROCESSAMENTO DE ARTIGOS (PDFs)")
        print(f"  Total de Artigos Encontrados: {total_articles}")
        for status, count in article_stats.items():
            print(f"  - {status.ljust(15)}: {count}")
            
        print_section("EXTRAÇÃO DE AUTORES")
        print(f"  Total de Autores Encontrados: {total_authors}")

        print_section("VERIFICAÇÃO DE EMAILS")
        print(f"  Total de Emails Capturados: {total_emails}")
        print(f"  VÁLIDOS (Limpos):   \033[92m{valid_emails}\033[0m") # Green
        print(f"  INVÁLIDOS:          \033[91m{invalid_emails}\033[0m") # Red
        print(f"  Pendente/Processando: {pending_emails + processing_emails}")
        
        print_section("RESUMO")
        print(f"  EMAILS LIMPOS PRONTOS: {valid_emails}")
        print(f"  AUTORES ENCONTRADOS:   {total_authors}")
        
        remaining_editions = found_editions
        if remaining_editions > 0:
            print(f"  Edições aguardando crawling: {remaining_editions}")
        else:
            print(f"  Nenhuma edição pendente descoberta (rodar discovery pode encontrar mais).")

    except Exception as e:
        print(f"Erro ao consultar banco de dados: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    main()
