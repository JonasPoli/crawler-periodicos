#!/usr/bin/env python3
"""
import_qualis.py - Imports Qualis ratings from the Sucupira Excel file.

Reads docs/sucupira.xlsx and matches journals in the database by ISSN
(both print and electronic). Updates the 'qualis' and 'subject_area' fields.

If a journal matches multiple Qualis entries (different areas), the best
(highest) Qualis is used.
"""

import pandas as pd
from database import get_session, Journal
import sys
import os

QUALIS_RANK = {
    'A1': 1, 'A2': 2, 'A3': 3, 'A4': 4,
    'B1': 5, 'B2': 6, 'B3': 7, 'B4': 8,
    'C': 9
}

def best_qualis(q1, q2):
    """Return the better (higher ranked) Qualis."""
    if not q1: return q2
    if not q2: return q1
    return q1 if QUALIS_RANK.get(q1, 99) <= QUALIS_RANK.get(q2, 99) else q2


def main():
    xlsx_path = os.path.join(os.path.dirname(__file__), 'docs', 'sucupira.xlsx')
    
    if not os.path.exists(xlsx_path):
        print(f"Erro: Arquivo não encontrado: {xlsx_path}")
        print("Coloque o arquivo Excel do Sucupira em docs/sucupira.xlsx")
        sys.exit(1)
    
    print(f"Lendo {xlsx_path}...")
    df = pd.read_excel(xlsx_path)
    print(f"  {len(df)} registros carregados")
    
    # Build lookup: ISSN -> (best_qualis, area)
    issn_map = {}
    for _, row in df.iterrows():
        issn = str(row['ISSN']).strip()
        estrato = str(row['Estrato']).strip()
        area = str(row.get('Área de Avaliação', '')).strip()
        
        if issn and issn != 'nan':
            if issn in issn_map:
                existing_q, existing_a = issn_map[issn]
                better = best_qualis(existing_q, estrato)
                # Keep the area of the best qualis
                if better == estrato:
                    issn_map[issn] = (estrato, area)
                # else keep existing
            else:
                issn_map[issn] = (estrato, area)
    
    print(f"  {len(issn_map)} ISSNs únicos mapeados\n")
    
    session = get_session()
    journals = session.query(Journal).all()
    
    updated = 0
    already_ok = 0
    not_found = 0
    
    for journal in journals:
        # Try matching by issn_print, issn_electronic, or issn
        matched = None
        for issn_field in [journal.issn_print, journal.issn_electronic, journal.issn]:
            if issn_field and issn_field.strip() in issn_map:
                candidate = issn_map[issn_field.strip()]
                if matched:
                    # Keep better qualis if multiple ISSNs match 
                    better_q = best_qualis(matched[0], candidate[0])
                    if better_q == candidate[0]:
                        matched = candidate
                else:
                    matched = candidate
        
        if matched:
            new_qualis, new_area = matched
            
            # Only update if it improves the current value
            current_q = journal.qualis
            better = best_qualis(current_q, new_qualis)
            
            if current_q != better or not journal.subject_area:
                journal.qualis = better
                if new_area and new_area != 'nan':
                    journal.subject_area = new_area
                updated += 1
                print(f"  ✅ {journal.name}")
                print(f"     ISSN: p={journal.issn_print} e={journal.issn_electronic}")
                print(f"     Qualis: {current_q} -> {better} ({new_area})")
            else:
                already_ok += 1
        else:
            not_found += 1
            print(f"  ⚠️  Sem match: {journal.name} (p={journal.issn_print} e={journal.issn_electronic})")
    
    session.commit()
    
    print(f"\n{'='*60}")
    print(f"RESULTADO:")
    print(f"  Total periódicos:    {len(journals)}")
    print(f"  Atualizados:         {updated}")
    print(f"  Já corretos:         {already_ok}")
    print(f"  Sem match no Excel:  {not_found}")
    
    # Show final distribution
    from sqlalchemy import func
    dist = session.query(Journal.qualis, func.count()).group_by(Journal.qualis).all()
    print(f"\nDistribuição Qualis final:")
    for q, c in sorted(dist, key=lambda x: QUALIS_RANK.get(str(x[0]), 99)):
        print(f"  {q or 'Sem Qualis'}: {c}")


if __name__ == '__main__':
    main()
