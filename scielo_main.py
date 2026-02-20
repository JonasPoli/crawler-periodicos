from scielo_crawler import SciELOCrawler
from processor import Processor

def main():
    base_url = "https://www.scielo.br/j/rap"
    
    crawler = SciELOCrawler(base_url, download_dir='downloads_scielo')
    
    print("--- STARTING SCIELO CRAWLER ---")
    issues = crawler.get_all_issues()
    print(f"Found {len(issues)} issues.")
    
    # Process issues
    for issue in issues:
        pdf_links = crawler.get_pdf_links(issue)
        print(f"Issue {issue} has {len(pdf_links)} PDF links.")
        for link in pdf_links:
            crawler.download_pdf(link)
                
    print("--- CRAWLER FINISHED ---")
    
    print("--- STARTING PROCESSING ---")
    # Reuse Processor but point to new folders
    processor = Processor(download_dir='downloads_scielo', output_file='emails_scielo.csv')
    processor.process_all()
    print("--- PROCESSING FINISHED ---")

if __name__ == "__main__":
    main()
