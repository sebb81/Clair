"""Section-aware extractive context. Original text and source IDs are retained."""
import math
import re
import unicodedata
from collections import Counter, defaultdict

VERSION = 'extractive-sections-v1'
STOP = set('de des du le la les un une et en au aux pour par sur avec dans ce ces est sont qui que il elle on nous vous je mon ma mes leur se ne pas plus'.split())


def terms(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    return Counter(w for w in re.findall(r'\w+', text) if len(w) > 2 and w not in STOP)


def select(rows, sections, budget, count):
    complete = '\n\n'.join(f"[S{r['id']}] {r['title']}\n{r['text']}" for r in rows)
    if count(complete) <= budget:
        return complete, [r['id'] for r in rows], dict(
            partial=False, scope='all-extracted-blocks',
            sections=[dict(id=s['id'], title=s['title'], page=s['page'], selected=True) for s in sections],
            sections_selected=len(sections), sections_total=len(sections),
            pages_selected=sorted({r['page'] or r['block'] for r in rows}),
            passages=len(rows), evidence_tokens=count(complete), budget_tokens=budget,
            selected_source_ids=[r['id'] for r in rows])
    # Rejoin adjacent fragments before finding sentence boundaries. Every sentence
    # retains all original chunk IDs it overlaps, including split sentences.
    groups = []
    for row in rows:
        key = (row['section'], row['page'], row['block'])
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(row)
    candidates = []
    page_text = defaultdict(str)
    for row in rows:
        page_text[row['page'] or row['block']] += row['text'] + '\n'
    toc_pages = {p for p, text in page_text.items() if len(re.findall(r'\.{4,}', text)) >= 3}
    for (section, page, block), group in groups:
        if (page or block) in toc_pages:
            continue
        text, spans = '', []
        for row in group:
            start = len(text)
            text += row['text'] + '\n'
            spans.append((start, len(text), row['id']))
        for match in re.finditer(r'.+?(?:[.!?](?=\s|$)|\n(?=\s*[•#\-])|\Z)', text, re.S):
            passage = match.group().strip()
            words = terms(passage)
            # Dotted TOC rows, bare headings and repeated footers are poor evidence.
            if len(words) < 6 or re.search(r'\.{4,}', passage) or len(passage) > 2200:
                continue
            ids = [i for a, b, i in spans if a < match.end() and b > match.start()]
            body = ' '.join(f'[S{i}]' for i in ids) + ' ' + group[0]['title'] + '\n' + passage
            candidates.append(dict(text=body, passage=passage, ids=ids, section=section,
                                   page=page, block=block, terms=words, cost=count(body) + 4))
    frequencies = Counter(w for c in candidates for w in c['terms'])
    for c in candidates:
        c['score'] = sum((1 + math.log(v)) * math.log(2 + len(candidates) / frequencies[w])
                         for w, v in c['terms'].items()) / math.sqrt(max(1, c['cost']))
    by_section = defaultdict(list)
    for index, candidate in enumerate(candidates):
        by_section[candidate['section']].append(index)
    chosen, used, seen = [], 0, set()

    def add(indices):
        nonlocal used
        eligible = [i for i in indices if i not in chosen and used + candidates[i]['cost'] <= budget
                    and candidates[i]['passage'] not in seen]
        if not eligible:
            return False
        def score(i):
            words = set(candidates[i]['terms'])
            overlap = max((len(words & set(candidates[j]['terms'])) / max(1, len(words | set(candidates[j]['terms'])))
                           for j in chosen), default=0)
            return candidates[i]['score'] * (1 - .7 * overlap)
        i = max(eligible, key=score)
        chosen.append(i)
        seen.add(candidates[i]['passage'])
        used += candidates[i]['cost']
        return True

    # Breadth first: one representative for each detected section. If the budget
    # cannot hold those, distribute choices over the full document, not its prefix.
    # Reserve breadth across physical pages, including appendices that may all
    # belong to one extracted section. The number follows the passage costs.
    by_page = defaultdict(list)
    for i, candidate in enumerate(candidates):
        by_page[candidate['page'] or candidate['block']].append(i)
    remaining_pages = sorted(by_page)
    while remaining_pages and used < budget * .4:
        covered_pages = [candidates[i]['page'] or candidates[i]['block'] for i in chosen]
        page = max(remaining_pages, key=lambda p: min((abs(p - q) for q in covered_pages), default=p))
        add(by_page[page])
        remaining_pages.remove(page)
    ordered = list(by_section)
    representatives = [max(by_section[s], key=lambda i: candidates[i]['score']) for s in ordered]
    if used + sum(candidates[i]['cost'] for i in representatives) <= budget:
        for s in ordered:
            add(by_section[s])
    else:
        remaining = list(range(len(ordered)))
        while remaining:
            # Start, end, middle, then recursively fill the largest uncovered span.
            covered = [ordered.index(candidates[i]['section']) for i in chosen]
            pos = max(remaining, key=lambda p: min((abs(p - q) for q in covered), default=len(ordered)))
            add(by_section[ordered[pos]])
            remaining.remove(pos)
    while add(range(len(candidates))):
        pass
    selected = [candidates[i] for i in sorted(chosen)]
    evidence = '\n\n'.join(c['text'] for c in selected)
    # Cost is additive with an extra separator margin; also check joined BPE.
    while selected and count(evidence) > budget:
        selected.pop()
        evidence = '\n\n'.join(c['text'] for c in selected)
    selected_sections = {c['section'] for c in selected}
    section_report = [dict(id=s['id'], title=s['title'], page=s['page'],
                           selected=s['id'] in selected_sections,
                           eligible=s['id'] in by_section) for s in sections]
    all_pages = sorted({r['page'] or r['block'] for r in rows})
    selected_pages = sorted({c['page'] or c['block'] for c in selected})
    chapter_starts = {}
    for s in sections:
        match = re.match(r'chapitre\s+(\d+)\b', s['title'], re.I)
        if match and s['page'] not in toc_pages:
            chapter_starts[match.group(1)] = s
    starts = sorted(chapter_starts.values(), key=lambda s: s['page'])
    chapter_report = [dict(title=s['title'], page=s['page'],
                           selected_pages=[p for p in selected_pages if s['page'] <= p <
                                           (starts[i + 1]['page'] if i + 1 < len(starts) else
                                            min((sec['page'] for sec in sections if sec['page'] > s['page']
                                                 and sec['title'].lower().startswith('conclusion')),
                                                default=max(all_pages, default=0) + 1))])
                      for i, s in enumerate(starts)]
    coverage = dict(sections=section_report, sections_selected=len(selected_sections),
                    sections_total=len(sections), pages_selected=selected_pages,
                    pages_with_text=all_pages, passages=len(selected),
                    partial=True, scope='extracted-passages-only',
                    evidence_tokens=count(evidence), budget_tokens=budget,
                    selected_source_ids=sorted({i for c in selected for i in c['ids']}),
                    chapters=chapter_report, toc_pages_excluded=sorted(toc_pages),
                    pages_with_candidates=sorted(by_page))
    return evidence, coverage['selected_source_ids'], coverage
