from crawler import Crawler
from processor import Processor

def main():
    base_url = "https://ojs.studiespublicacoes.com.br/ojs/index.php/cadped"
    archive_url = f"{base_url}/issue/archive"
    
    crawler = Crawler(base_url)
    
    print("--- STARTING CRAWLER ---")
    # issues = crawler.get_issues_by_range(165, 1)
    # User requested archive pagination
    issues = crawler.get_all_archive_issues(archive_url)
    print(f"Found {len(issues)} issues across all archive pages.")
    
    # Limit for testing? User said "baixe todos os PDFs", so we do all.
    # But usually good to test with a few first.
    # We will try to get all.
    
    for issue in issues:
        articles = crawler.get_articles(issue)
        print(f"Issue {issue} has {len(articles)} articles.")
        for article in articles:
            pdf_link = crawler.get_pdf_link(article)
            if pdf_link:
                crawler.download_pdf(pdf_link)
            else:
                # Fallback or specific logic might be needed
                pass
                
    print("--- CRAWLER FINISHED ---")
    
    print("--- STARTING PROCESSING ---")
    processor = Processor()
    processor.process_all()
    print("--- PROCESSING FINISHED ---")

if __name__ == "__main__":
    main()
