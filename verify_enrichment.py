from database import get_session, Article, Author, Keyword, Reference

def verify():
    session = get_session()
    # Get enriched articles
    articles = session.query(Article).filter(Article.status == 'metadata_enriched').limit(5).all()
    
    print(f"Verifying {len(articles)} enriched articles...\n")
    
    for art in articles:
        print(f"ID: {art.id}")
        print(f"Title: {art.title[:50]}...")
        print(f"Resumo (len): {len(art.abstract) if art.abstract else 0}")
        print(f"Abstract EN (len): {len(art.abstract_en) if art.abstract_en else 0}")
        print(f"Pub Date: {art.publication_date}")
        print(f"DOI: {art.doi}")
        
        print("Authors:")
        for au in art.authors:
            print(f"  - {au.name} (ORCID: {au.orcid})")
            
        print(f"Keywords ({len(art.keywords)}):")
        print(f"  {', '.join([k.value for k in art.keywords])}")
            
        print(f"References ({len(art.references)}):")
        for ref in art.references[:3]:
            print(f"  - {ref.text[:100]}...")
        if len(art.references) > 3:
            print("  ...")
            
        print("-" * 50)

if __name__ == "__main__":
    verify()
