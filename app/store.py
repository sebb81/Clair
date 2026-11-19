import json
import sqlite3
from contextlib import contextmanager

from .config import settings


@contextmanager
def db():
    conn = sqlite3.connect(settings.data_dir / 'documents.sqlite', timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    with db() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            path TEXT NOT NULL, pages INTEGER DEFAULT 0, chars INTEGER DEFAULT 0,
            status TEXT DEFAULT 'extracting', warnings TEXT DEFAULT '[]',
            extraction_ms REAL DEFAULT 0, created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS pages (
            doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            number INTEGER, text TEXT, tables TEXT, scanned INTEGER,
            PRIMARY KEY(doc,number));
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            title TEXT, page INTEGER, ordinal INTEGER);
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            section INTEGER, page INTEGER, block INTEGER, title TEXT, text TEXT, ordinal INTEGER);
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
            text, title, doc UNINDEXED, chunk UNINDEXED,
            tokenize='unicode61 remove_diacritics 2');
        CREATE TABLE IF NOT EXISTS summaries (
            key TEXT PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            level INTEGER, text TEXT, sources TEXT, model TEXT, duration_ms REAL);
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            question TEXT, answer TEXT, sources TEXT, metrics TEXT,
            created TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc, ordinal);
        CREATE INDEX IF NOT EXISTS summaries_doc ON summaries(doc);
        CREATE TABLE IF NOT EXISTS summary_roots (
            key TEXT PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            summary_key TEXT REFERENCES summaries(key) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS answer_cache (
            key TEXT PRIMARY KEY, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            answer TEXT, sources TEXT, metrics TEXT, warnings TEXT);
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY, run TEXT, doc TEXT REFERENCES documents(id) ON DELETE CASCADE,
            model TEXT, metrics TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
        ''')


def document(doc):
    with db() as c:
        r = c.execute('SELECT * FROM documents WHERE id=?', (doc,)).fetchone()
        if r is None:
            raise KeyError('Document introuvable.')
        result = dict(r)
        result.pop('path', None)
        result['warnings'] = json.loads(result['warnings'])
        result['sections'] = [dict(s) for s in c.execute(
            'SELECT * FROM sections WHERE doc=? ORDER BY ordinal LIMIT 5000', (doc,))]
        result['chunks'] = c.execute('SELECT count(*) FROM chunks WHERE doc=?', (doc,)).fetchone()[0]
        result['summaries_cached'] = c.execute('SELECT count(*) FROM summaries WHERE doc=?', (doc,)).fetchone()[0]
        return result


def chunks(doc, section=None):
    with db() as c:
        sql = 'SELECT * FROM chunks WHERE doc=?'
        args = [doc]
        if section is not None:
            sql += ' AND section=?'
            args.append(section)
        # Text is read by a cursor, never fetchall for the complete document.
        for row in c.execute(sql + ' ORDER BY ordinal', args):
            yield dict(row)


def sources(ids):
    result = []
    with db() as c:
        for chunk_id in sorted(set(ids)):
            row = c.execute('SELECT id,page,block,title,text,section FROM chunks WHERE id=?', (chunk_id,)).fetchone()
            if row:
                result.append(dict(row))
    return result
