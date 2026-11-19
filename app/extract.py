import hashlib
import json
import re
import time
import zipfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .config import settings
from .store import db, document

VERSION = 'extract-v4'
HEADING = re.compile(r'^(?:#{1,6}\s+|(?:chapitre|section|partie)\s+[\wIVX]+|\d+(?:\.\d+)*[.)]?\s+\S)', re.I)


def heading(text):
    return len(text) <= 160 and (bool(HEADING.match(text)) or (len(text) > 5 and text.isupper()))


def split_text(text, max_bytes=1100):
    """Split on paragraphs/sentences/words, with a hard byte bound even for CJK."""
    current = ''
    for paragraph in text.splitlines():
        for word in re.findall(r'\S+\s*', paragraph + '\n'):
            if len((current + word).encode('utf-8')) > max_bytes and current:
                yield current.strip()
                current = ''
            # A single unbroken token may itself exceed the budget.
            for char in word:
                if len((current + char).encode('utf-8')) > max_bytes:
                    yield current.strip()
                    current = ''
                current += char
    if current.strip():
        yield current.strip()


def pdf_pages(path):
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError('PDF chiffré : retirez le mot de passe avant importation.')
        toc = {row[2]: row[1] for row in pdf.get_toc()}
        for i, page in enumerate(pdf):
            text = page.get_text(sort=True)
            tables, warnings = [], []
            try:
                for table in page.find_tables().tables:
                    tables.append(table.extract())
            except Exception:
                warnings.append(f'Détection des tableaux incomplète, page {i + 1}.')
            # Include structured tables in searchable text, retaining the page.
            if tables:
                text += '\n\n' + '\n\n'.join('\n'.join(' | '.join(str(v or '') for v in row) for row in t) for t in tables)
            scanned = len(text.strip()) < 30 and bool(page.get_images())
            yield i + 1, text, tables, scanned, toc.get(i + 1), warnings


def docx_pages(path):
    with zipfile.ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > settings.max_text_mb * 1024 * 1024:
            raise ValueError('DOCX décompressé trop volumineux.')
    doc = Document(path)
    # DOCX has no stable pagination without a layout engine. Emit logical blocks.
    text, tables = [], []
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            if item.style and item.style.name.startswith('Heading'):
                text.append('# ' + item.text)
            else:
                text.append(item.text)
        elif isinstance(item, Table):
            rows = [[cell.text for cell in row.cells] for row in item.rows]
            tables.append(rows)
            text.append('\n'.join(' | '.join(row) for row in rows))
        if sum(len(v) for v in text) > 6000:
            yield 0, '\n'.join(text), tables, False, None, []
            text, tables = [], []
    if text:
        yield 0, '\n'.join(text), tables, False, None, []


def txt_pages(path):
    # Read bounded logical blocks; form feeds retain genuine explicit pagination.
    with open(path, encoding='utf-8-sig', errors='strict') as stream:
        buffer = ''
        for line in stream:
            if len(line.encode('utf-8')) > 2 * 1024 * 1024:
                raise ValueError('Ligne TXT trop longue (maximum 2 Mo).')
            buffer += line
            if len(buffer) >= 6000:
                yield 0, buffer, [], False, None, []
                buffer = ''
        if buffer:
            yield 0, buffer, [], False, None, []


def extract(path: Path, name: str, digest: str):
    started = time.perf_counter()
    kind = path.suffix.lower().lstrip('.')
    doc_id = hashlib.sha256((digest + VERSION).encode()).hexdigest()[:24]
    with db() as c:
        old = c.execute('SELECT status FROM documents WHERE id=?', (doc_id,)).fetchone()
        if old and old['status'] == 'ready':
            return document(doc_id), True
        if old:
            c.execute('DELETE FROM search WHERE doc=?', (doc_id,))
            c.execute('DELETE FROM documents WHERE id=?', (doc_id,))
        c.execute('INSERT INTO documents(id,name,kind,path) VALUES (?,?,?,?)', (doc_id, name, kind, str(path)))
    readers = {'pdf': pdf_pages, 'docx': docx_pages, 'txt': txt_pages}
    warnings, total, ordinal, section_order, logical_page = [], 0, 0, 0, 0
    current_title, section_id = 'Début du document', None
    try:
        with db() as c:
            for page_num, text, tables, scanned, toc_title, page_warnings in readers[kind](path):
                logical_page += 1
                stored_page = page_num or logical_page
                total += len(text.encode('utf-8'))
                if total > settings.max_text_mb * 1024 * 1024:
                    raise ValueError('Texte extrait trop volumineux pour la limite configurée.')
                warnings.extend(page_warnings)
                if scanned:
                    warnings.append(f'Page {stored_page} probablement scannée : OCR local requis, texte non exploitable.')
                c.execute('INSERT INTO pages VALUES (?,?,?,?,?)',
                          (doc_id, stored_page, text, json.dumps(tables, ensure_ascii=False), int(scanned)))
                buffer = []

                def flush():
                    nonlocal ordinal
                    for part in split_text('\n'.join(buffer)):
                        ordinal += 1
                        cur = c.execute('INSERT INTO chunks(doc,section,page,block,title,text,ordinal) VALUES (?,?,?,?,?,?,?)',
                                        (doc_id, section_id, page_num or None, stored_page, current_title, part, ordinal))
                        c.execute('INSERT INTO search(text,title,doc,chunk) VALUES (?,?,?,?)',
                                  (part, current_title, doc_id, cur.lastrowid))
                    buffer.clear()

                for line in ([toc_title] if toc_title else []) + text.splitlines():
                    if section_id is not None and line.strip().lstrip('# ').strip() == current_title:
                        buffer.append(line)
                        continue
                    if line and (heading(line.strip()) or section_id is None or line == toc_title):
                        flush()
                        current_title = line.strip().lstrip('# ').strip()[:160]
                        section_order += 1
                        section_id = c.execute('INSERT INTO sections(doc,title,page,ordinal) VALUES (?,?,?,?)',
                                               (doc_id, current_title, stored_page, section_order)).lastrowid
                    buffer.append(line)
                flush()
            if kind != 'pdf':
                warnings.append('Pagination physique indisponible : les sources renvoient aux sections et blocs de texte.')
            if total == 0:
                warnings.append('Aucun texte extrait. Pour un scan, un OCR local est nécessaire.')
            c.execute('UPDATE documents SET pages=?,chars=?,status=?,warnings=?,extraction_ms=? WHERE id=?',
                      (logical_page, total, 'ready', json.dumps(warnings, ensure_ascii=False),
                       (time.perf_counter() - started) * 1000, doc_id))
    except BaseException:
        with db() as c:
            c.execute('DELETE FROM search WHERE doc=?', (doc_id,))
            c.execute('DELETE FROM documents WHERE id=?', (doc_id,))
        raise
    return document(doc_id), False
