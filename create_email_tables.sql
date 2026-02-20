CREATE TABLE IF NOT EXISTS email_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain VARCHAR(255) UNIQUE NOT NULL,
    has_dns BOOLEAN,
    has_mx BOOLEAN,
    mx_records TEXT,
    checked_at DATETIME
);

CREATE TABLE IF NOT EXISTS email_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    domain_id INTEGER,
    format_valid BOOLEAN,
    domain_valid BOOLEAN,
    mx_valid BOOLEAN,
    smtp_valid BOOLEAN,
    final_status VARCHAR(50),
    checked_at DATETIME,
    FOREIGN KEY(domain_id) REFERENCES email_domains(id)
);
