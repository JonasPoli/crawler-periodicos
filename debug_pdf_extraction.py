import sys
import os

# Ensure we can import processor
sys.path.append(os.getcwd())

from processor import Processor

def debug_pdf(pdf_path):
    proc = Processor()
    
    print(f"--- Analyzing {pdf_path} ---")
    
    # Try pypdf
    text_pypdf = proc._extract_with_pypdf(pdf_path)
    print("\n[pypdf extraction sample (first 500 chars)]:")
    print(text_pypdf[:500])
    
    # Try pdfplumber
    text_plumber = proc._extract_with_pdfplumber(pdf_path)
    print("\n[pdfplumber extraction sample (first 500 chars)]:")
    print(text_plumber[:500])
    
    # Combined extraction
    full_text = proc.extract_text_from_pdf(pdf_path)
    emails = proc.extract_emails(full_text)
    
    print("\n[Extracted Emails]:")
    for email in emails:
        print(email)

    expected = [
        "catize.brandelero@ufsm.br",
        "gabriel@gabrielberger.com.br",
        "edvaldofaour@gmail.com",
        "erika.nunes@acad.ufsm.edu.br",
        "alexandrerussini@unipampa.edu.br",
        "luana.lovato@acad.ufsm.br",
        "josias-junior.1@acad.ufsm.br",
        "daniela.herzog@acad.ufsm.br"
    ]
    
    print("\n[Missing Expected Emails]:")
    for exp in expected:
        if exp not in emails:
            print(f"MISSING: {exp}")

if __name__ == "__main__":
    pdf_file = "downloads/5854_3842.pdf"
    if len(sys.argv) > 1:
        pdf_file = sys.argv[1]
        
    debug_pdf(pdf_file)
