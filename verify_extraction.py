from processor import Processor
import sys
import os

def verify(path):
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return

    print(f"Testing extraction on: {path}")
    
    p = Processor()
    # Processor usually takes db_manager but we can mock it or check if it's needed for extraction
    # Looking at code, extract_emails_from_pdf seems self-contained?
    # Let's check source of likely `extract_text_from_pdf` and `extract_emails`
    
    text = p.extract_text_from_pdf(path)
    print(f"Extracted {len(text)} chars.")
    
    emails = p.extract_emails(text)
    print(f"Emails found: {emails}")
    
    # Print a snippets around @
    if not emails:
        print("Debugging context around @ symbols:")
        lines = text.split('\n')
        for i, line in enumerate(lines):
            if '@' in line:
                print(f"  Line {i}: {line.strip()}")

if __name__ == "__main__":
    verify(sys.argv[1])
