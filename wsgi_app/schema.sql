CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    mtime REAL NOT NULL,
    rendered_html TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    frontmatter_json TEXT
);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    title,
    body,
    content='files',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
    INSERT INTO files_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY,
    attempted_at REAL NOT NULL,
    success INTEGER NOT NULL
);
