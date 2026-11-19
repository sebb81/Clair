"""Isolated CPU-only passage-selection experiment; does not call an LLM.

Run from the project root with: python -m scripts.benchmark_extractive DOCUMENT_ID
The original document, summaries and history are read only. Reports stay in data/.
This is a candidate selector, not a validated complete summary.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import statistics
import time
import unicodedata

from app.store import chunks, document


STOP = set('''a ai aient ainsi alors apres au aucun aussi autre aux avec avoir avons ce ceci cela
ces cet cette ceux chaque chez comme comment dans de des du depuis donc dont elle elles en encore
entre est et etaient etait etre eu eux fait faire faut il ils je la le les leur leurs lui ma mais me
mes meme moi mon ne ni nos notre nous on ont ou par parce pas pendant peut plus pour pourquoi puis
qu quand que quel quelle quelles quels qui sa sans se sera ses si son sont sous sur ta te tes toi
ton tous tout toute toutes tres tu un une vos votre vous y c d j l m n qu s t etc afin notamment
permet permettre cadre competence competences definition origine contexte demarche activites
realisees analyse exemple fourni fournie annexe dossier validation leo benazeth page'''.split())


def terms(text):
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))
    return [w for w in re.findall(r'\b\w+\b', text) if len(w) > 2 and w not in STOP]


def dot(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(value * b.get(word, 0) for word, value in a.items())


def unit(vector):
    norm = math.sqrt(sum(v * v for v in vector.values())) or 1
    return {word: value / norm for word, value in vector.items()}


def select(rows, pages, byte_budget):
    candidates, counts = [], []
    for row in rows:
        # Ranking sees every extracted chunk; dotted TOC rows and tiny fragments
        # are not useful candidates for this first experiment.
        text = row['text']
        words = terms(text)
        if len(words) < 25 or len(re.findall(r'\.{4,}', text)) >= 3:
            continue
        candidates.append(row)
        counts.append(Counter(words))
    if not candidates:
        raise ValueError('No candidate passages found')
    frequencies = Counter(word for count in counts for word in count)
    vectors = [unit({word: (1 + math.log(freq)) * (1 + math.log((1 + len(counts)) / (1 + frequencies[word])))
                     for word, freq in count.items()}) for count in counts]
    centroid = Counter()
    for vector in vectors:
        centroid.update(vector)
    centroid = unit(centroid)
    relevance = [dot(v, centroid) for v in vectors]
    highest = max(relevance) or 1
    relevance = [score / highest for score in relevance]
    chosen, used = [], 0
    band_width = max(1, math.ceil(pages / 12))
    bands = [(max(1, row['page'] or row['block']) - 1) // band_width for row in candidates]

    def score(index):
        redundancy = max((dot(vectors[index], vectors[j]) for j in chosen), default=0)
        # Bias toward informative, explicit statements without requiring a model.
        text = candidates[index]['text']
        richness = min(len(re.findall(r'\b\d+(?:[.,]\d+)?\b', text)), 4) / 4
        return .72 * relevance[index] + .08 * richness - .35 * redundancy

    def add_best(indices):
        nonlocal used
        available = [i for i in indices if i not in chosen and used + len(candidates[i]['text'].encode('utf-8')) <= byte_budget]
        if not available:
            return False
        index = max(available, key=score)
        chosen.append(index)
        used += len(candidates[index]['text'].encode('utf-8'))
        return True

    # A document-wide selection, not retrieval for the words "résume ce PDF".
    # Page bands provide a simple coverage constraint; chapter-aware selection
    # and a check for omitted important facts would be required before adoption.
    for band in sorted(set(bands)):
        add_best([i for i, current in enumerate(bands) if current == band])
    while add_best(range(len(candidates))):
        pass
    selected = sorted((candidates[i] for i in chosen), key=lambda row: row['ordinal'])
    return selected, len(candidates), len(set(bands)), len({bands[i] for i in chosen})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('document_id')
    parser.add_argument('--max-bytes', type=int, default=12000)
    args = parser.parse_args()
    started = time.perf_counter()
    info = document(args.document_id)
    rows = list(chunks(args.document_id))
    read_ms = (time.perf_counter() - started) * 1000
    durations = []
    for _ in range(3):
        started = time.perf_counter()
        selected, eligible, bands, selected_bands = select(rows, info['pages'], args.max_bytes)
        durations.append((time.perf_counter() - started) * 1000)
    source_bytes = sum(len(row['text'].encode('utf-8')) for row in rows)
    selected_bytes = sum(len(row['text'].encode('utf-8')) for row in selected)
    stats = {
        'document': args.document_id, 'pdf_pages': info['pages'],
        'chunks_read': len(rows), 'eligible_chunks': eligible,
        'selected_chunks': len(selected), 'source_text_bytes': source_bytes,
        'selected_text_bytes': selected_bytes,
        'reduction_percent': round(100 * (1 - selected_bytes / source_bytes), 2),
        'page_bands_with_candidates': bands, 'page_bands_selected': selected_bands,
        'selected_pages': sorted({row['page'] for row in selected}),
        'database_read_ms': round(read_ms, 2),
        'selection_ms_three_runs': [round(value, 2) for value in durations],
        'selection_median_ms': round(statistics.median(durations), 2),
        'llm_calls': 0, 'machine': 'development PC, not target Dell',
        'limits': [
            'Existing extracted text; PDF extraction time is excluded.',
            'Passage selection only; no generated rewrite is timed.',
            'Coverage of page bands does not prove semantic completeness.',
            'Content quality and performance on target Dell are not validated.',
        ],
    }
    output = Path('data')
    (output / 'extractive-experiment.json').write_text(
        json.dumps({'metrics': stats, 'passages': selected}, ensure_ascii=False, indent=2), encoding='utf-8')
    parts = ['# Passages sélectionnés — essai extractif\n',
             'Sélection expérimentale, pas un résumé complet validé. Texte original sans reformulation.\n']
    for row in selected:
        parts.extend([f"## Page {row['page']} — S{row['id']} — {row['title']}\n", row['text'] + '\n'])
    (output / 'extractive-experiment.md').write_text('\n'.join(parts), encoding='utf-8')
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
