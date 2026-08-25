#!/usr/bin/env python3
import csv
import os
import io
from database import get_session, Journal

OUTPUT_CSV = 'revistas.csv'

def export_journals(output_path=OUTPUT_CSV):
    session = get_session()
    journals = session.query(Journal).order_by(Journal.name).all()
    
    print(f"Exportando {len(journals)} periódicos para '{output_path}'...")
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['issn', 'title', 'qualis', 'area'])
        
        for j in journals:
            # Resolve ISSN candidates
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
            writer.writerow([issn_val, title_val, qualis_val, area_val])
            
    print(f"Exportação concluída com sucesso em '{output_path}'.")

if __name__ == '__main__':
    export_journals()
