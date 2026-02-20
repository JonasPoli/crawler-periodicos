SELECT 
    -- Author Details
    au.id AS author_id,
    au.name AS author_name,
    au.email AS author_email,
    au.affiliation AS author_affiliation,
    au.created_at AS author_created_at,

    -- Journal Details (Revista)
    j.id AS journal_id,
    j.name AS journal_name,
    j.acronym AS journal_acronym,
    j.issn AS journal_issn,
    j.source_type AS journal_source_type,
    j.url AS journal_url,

    -- Edition Details
    ed.id AS edition_id,
    ed.volume AS edition_volume,
    ed.number AS edition_number,
    ed.year AS edition_year,
    ed.title AS edition_title,

    -- Article Details (Artigo)
    ar.id AS article_id,
    ar.title AS article_title,
    ar.doi AS article_doi,
    ar.url AS article_url,
    ar.published_date AS article_published_date,
    ar.status AS article_status,

    -- File Details (related to article)
    f.id AS file_id,
    f.file_type AS file_type,
    f.local_path AS file_local_path,
    f.url AS file_url

FROM authors au
-- Join with Article Authors (Bridge table)
LEFT JOIN article_authors aa ON au.id = aa.author_id
-- Join with Articles
LEFT JOIN articles ar ON aa.article_id = ar.id
-- Join with Editions
LEFT JOIN editions ed ON ar.edition_id = ed.id
-- Join with Journals
LEFT JOIN journals j ON ed.journal_id = j.id
-- Join with Files
LEFT JOIN files f ON ar.id = f.article_id

ORDER BY au.id;
