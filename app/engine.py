import asyncio
import hashlib
import json
import re
import time
import unicodedata
from contextlib import aclosing

from . import llamacpp, llm, selection, token_budget, summary, webnn, wllama
from .config import settings
from .store import chunks, db, document, sources

PROMPT_VERSION = 'hierarchy-v7'
SUMMARY_QUESTION = ('Condense uniquement les faits explicitement présents en préservant leur sens. '
                    'Conserve les noms, dates, montants, risques et décisions. '
                    'Ne dis jamais qu’une catégorie est absente. Ne cite pas les consignes de rédaction. '
                    'Le champ summary contient les faits, le champ source_ids leurs identifiants numériques.')
SUMMARY_GENERATION_QUESTION = (
    'Sélectionne les faits principaux et condense-les en 70 mots maximum. '
    'Préserve les noms et les chiffres des faits retenus, sans chercher à tout énumérer. '
    'N’ajoute aucun fait ni constat d’absence. '
    'Retourne un objet JSON complet avec summary et source_ids, sans doublons dans source_ids.')
FAST_POLICY = ('Décris ce que rapporte le document, sans jugement de valeur. '
               'Distingue ce qui est réalisé, proposé, simulé ou validé : une compétence visée '
               'ne prouve pas une validation obtenue. Pour chaque paragraphe, choisis d’abord '
               'les source_ids puis écris uniquement les faits justifiés par ces sources. '
               'Conserve les réserves et hypothèses. Répartis la synthèse entre les grands thèmes du document.')
STOP = set('quel quelle quels quelles est sont le la les un une du de des au aux en pour par avec et ou ce cet cette ces dans sur moi fais faire donne peux tu il y a ne pas annonce annoncé annoncée document chapitre resume résume résumé budget'.split()) - {'budget'}


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def search(doc, question, limit=10, section=None):
    words = list(dict.fromkeys(w for w in re.findall(r'\w+', normalize(question))
                              if len(w) > 1 and w not in {normalize(s) for s in STOP}))[:30]
    if not words:
        return []
    query = ' OR '.join('"' + w + '"' for w in words)
    with db() as c:
        sql = '''SELECT chunks.*, bm25(search,1,2) score FROM search
                 JOIN chunks ON chunks.id=search.chunk
                 WHERE search MATCH ? AND search.doc=?'''
        args = [query, doc]
        if section is not None:
            sql += ' AND chunks.section=?'
            args.append(section)
        rows = [dict(r) for r in c.execute(sql + ' ORDER BY score LIMIT ?', (*args, limit))]
    # Require exact year/entity coverage if specified; never answer a different year's budget.
    years = re.findall(r'\b(?:19|20|21)\d{2}\b', question)
    if years:
        rows = [r for r in rows if all(year in r['text'] for year in years)]
    return rows


def route(question):
    q = normalize(question)
    if re.search(r'\b(chapitre|section|partie)\s+[\w.-]+', q):
        return 'section'
    if any(w in q for w in ['contradiction', 'compare', 'transversal', 'divergence']):
        return 'hybrid'
    if any(w in q for w in ['resume', 'synthese', 'points importants', 'points cles', 'risques', 'decisions', 'termes simples']):
        return 'summary'
    return 'bm25'


def source_text(row):
    return f"[S{row['id']}] {row['title']}\n{row['text']}"


def pack(rows, budget, count=llm.token_estimate):
    selected, parts, duplicates, used = [], [], {}, 0
    for row in rows:
        # Only exact duplicates with the same heading can share a source body.
        # Keep every original ID, including references to different physical pages.
        duplicate_key = (row['title'], row['text'])
        if duplicate_key in duplicates:
            alias = f"[S{row['id']}] "
            cost = count(alias)
            if used + cost <= budget:
                index = duplicates[duplicate_key]
                parts[index] = alias + parts[index]
                selected.append(row['id'])
                used += cost
            continue
        text = source_text(row)
        cost = count(text) + 2
        if used + cost > budget:
            continue
        selected.append(row['id'])
        duplicates[duplicate_key] = len(parts)
        parts.append(text)
        used += cost
    return '\n\n'.join(parts), selected


def batches(nodes, budget):
    group, used = [], 0
    for node in nodes:
        cost = llm.token_estimate(node['text']) + 4
        if cost > budget:
            raise llm.ModelError('Un bloc dépasse le contexte configuré. Augmentez LOCALDOC_CONTEXT.')
        if used + cost > budget and group:
            yield group
            group, used = [], 0
        group.append(node)
        used += cost
    if group:
        yield group


def summary_context(level):
    return max(settings.context, settings.summary_context) if level >= 3 else settings.context


def summary_key(nodes, level, digest, version=PROMPT_VERSION, context=None):
    evidence = '\n\n'.join(n['text'] for n in nodes)
    ids = sorted({i for n in nodes for i in n['ids']})
    # 320 remains the layout reservation so the existing batch boundaries remain
    # resumable. v7 identifies the new generation and bounded retry policy.
    context = context or (summary_context(level) if version == PROMPT_VERSION else settings.context)
    return hashlib.sha256(json.dumps([version, llm.SYSTEM, SUMMARY_QUESTION, 320, digest, context, settings.threads,
                                   level, evidence, ids], ensure_ascii=False).encode()).hexdigest()


def cached_node(doc, nodes, level, digest):
    with db() as c:
        # Completed v6 summaries passed the same citation/truncation validation.
        # A change to retry behavior must not discard hours of successful work.
        for version in (PROMPT_VERSION, 'hierarchy-v6'):
            for context in dict.fromkeys((summary_context(level), settings.context)):
                key = summary_key(nodes, level, digest, version, context)
                cached = c.execute('SELECT text FROM summaries WHERE key=? AND doc=?', (key, doc)).fetchone()
                if cached:
                    return {'text': cached['text'], 'ids': sorted({i for n in nodes for i in n['ids']})}


def completed(progress, cached=False):
    progress['completed'] += 1
    progress['stage_completed'] = progress.get('stage_completed', 0) + 1
    if cached:
        progress['cached'] += 1


def fingerprint(*values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def root_key(doc, digest):
    return fingerprint(doc, digest, PROMPT_VERSION, llm.SYSTEM, SUMMARY_QUESTION,
                       SUMMARY_GENERATION_QUESTION, settings.context, summary_context(3), settings.threads)


def answer_policy(output_format):
    # Ask for brevity before enforcing a ceiling; truncating a long answer alone
    # would lose facts and citations. Explicit detailed answers retain their budget.
    if output_format == 'réponse courte':
        return output_format + ', 70 mots maximum, réponse directe avec citations', 256
    if output_format == 'points clés':
        return output_format + ', 5 points maximum, 120 mots maximum avec citations', 384
    return output_format + ', 200 mots maximum, sans introduction ni répétition', settings.answer_tokens


async def summarize_node(doc, nodes, level, model, digest, cancel, progress):
    if cancel and cancel.is_set():
        raise InterruptedError('Préparation interrompue ; les lots terminés sont conservés.')
    cached = cached_node(doc, nodes, level, digest)
    if cached:
        completed(progress, cached=True)
        return cached
    evidence = '\n\n'.join(n['text'] for n in nodes)
    ids = sorted({i for n in nodes for i in n['ids']})
    key = summary_key(nodes, level, digest)
    context = summary_context(level)
    question = SUMMARY_GENERATION_QUESTION
    generation_ms = 0
    evidence_ids = sorted({int(v) for v in re.findall(r'\[S(\d+)\]', evidence)} & set(ids))
    schema = {'type': 'object', 'properties': {
        'summary': {'type': 'string'},
        'source_ids': {'type': 'array', 'items': {'type': 'integer', 'enum': evidence_ids}, 'minItems': 1}},
        'required': ['summary', 'source_ids'], 'additionalProperties': False}
    word_limits = (160, 100) if level == 4 else (70, 40)
    for attempt, words in enumerate(word_limits):
        if cancel and cancel.is_set():
            raise InterruptedError('Préparation interrompue ; reprise possible.')
        output_format = f'JSON complet : summary en {words} mots maximum, puis source_ids.'
        attempt_question = question.replace('70 mots', f'{words} mots')
        estimated = sum(llm.token_estimate(m['content']) for m in llm.prompt(attempt_question, evidence, output_format)) + 180
        # Reserve from the actual prompt, including its citation list. Increasing
        # the context or discarding source text is not needed for a longer output.
        reserve = min(768 if not attempt else 1024, context - estimated)
        if reserve < 256:
            raise llm.ModelError('Contexte insuffisant pour terminer ce lot de synthèse ; les lots terminés sont conservés.')
        text, metrics = '', {}
        progress['calls'] += 1
        if attempt:
            progress['retries'] = progress.get('retries', 0) + 1
        async for event in llm.generate(model, attempt_question, evidence, output_format, reserve, schema=schema, context=context):
            if cancel and cancel.is_set():
                raise InterruptedError('Préparation interrompue ; reprise possible.')
            if event['type'] == 'token':
                text += event['text']
            else:
                metrics = event['metrics']
        generation_ms += metrics.get('generation_ms', 0)
        if metrics.get('done_reason') != 'length':
            break
    else:
        raise llm.ModelError('Ce lot reste tronqué après deux tentatives de condensation. Les lots terminés sont conservés ; aucun résumé incomplet n’a été enregistré.')
    if not text.strip():
        raise llm.ModelError('Le modèle a retourné un résumé vide.')
    try:
        structured = json.loads(text)
        cited = structured['source_ids']
        if not isinstance(cited, list) or not cited or any(type(i) is not int or i not in evidence_ids for i in cited):
            raise ValueError('identifiants invalides')
        if not isinstance(structured['summary'], str) or not structured['summary'].strip():
            raise ValueError('synthèse vide')
        text, invalid = llm.validate_citations(structured['summary'], ids)
        if invalid:
            raise ValueError('citations invalides')
        text += '\nSources : ' + ' '.join(f'[S{i}]' for i in sorted(set(cited)))
    except (ValueError, KeyError, TypeError) as exc:
        raise llm.ModelError('Résumé structuré sans références valides : il ne sera pas mis en cache.') from exc
    with db() as c:
        c.execute('INSERT OR IGNORE INTO summaries VALUES (?,?,?,?,?,?,?)',
                  (key, doc, level, text, json.dumps(ids), model, generation_ms))
    completed(progress)
    return {'text': text, 'ids': ids}


def legacy_leaf_groups(doc, budget):
    """Recognize already completed batches without invalidating their cache."""
    current_section, group = None, []
    for row in chunks(doc):
        if current_section is not None and row['section'] != current_section:
            yield from batches(group, budget)
            group = []
        current_section = row['section']
        group.append({'text': source_text(row), 'ids': [row['id']]})
        if sum(llm.token_estimate(n['text']) + 4 for n in group) > budget:
            last = group.pop()
            yield from batches(group, budget)
            group = [last]
    yield from batches(group, budget)


def leaf_plan(doc, budget, digest):
    # Keep valid old batches in their original position. Pack missing text across
    # section boundaries, which often contain only a title or a table-of-contents row.
    pending = []
    for group in legacy_leaf_groups(doc, budget):
        cached = cached_node(doc, group, 2, digest)
        if cached:
            for batch in batches(pending, budget):
                yield batch, None
            pending = []
            yield group, cached
        else:
            pending.extend(group)
            # Bound working memory to approximately two batches.
            groups = list(batches(pending, budget))
            for batch in groups[:-1]:
                yield batch, None
            pending = groups[-1] if groups else []
    for batch in batches(pending, budget):
        yield batch, None


async def prepare(doc, model, digest, cancel=None, progress=None):
    if model in token_budget.COUNTERS or model == llamacpp.MODEL or model in wllama.DEVICES:
        return await summary.prepare(doc, model, digest, cancel, progress)
    return await _prepare_legacy(doc, model, digest, cancel, progress)


async def _prepare_legacy(doc, model, digest, cancel=None, progress=None):
    progress = progress if progress is not None else {}
    progress.update(completed=0, cached=0, calls=0, stage='lecture du document', stage_completed=0)
    if cancel and cancel.is_set():
        raise InterruptedError('Préparation interrompue ; les lots terminés sont conservés.')
    root_cache_key = root_key(doc, digest)
    with db() as c:
        cached = c.execute('''SELECT s.text,s.sources FROM summary_roots r
                              JOIN summaries s ON s.key=r.summary_key AND s.doc=r.doc
                              WHERE r.key=? AND r.doc=?''', (root_cache_key, doc)).fetchone()
    if cached:
        progress.update(stage='synthèse globale', stage_total=1)
        completed(progress, cached=True)
        return {'text': cached['text'], 'ids': json.loads(cached['sources'])}
    question = SUMMARY_QUESTION
    budget = llm.evidence_budget(question, 'synthèse structurée, 120 mots maximum', 320)
    if budget < 1300:
        raise llm.ModelError('Contexte insuffisant pour les résumés : utilisez au moins 4096 tokens.')
    leaves = []
    # Only summaries and source IDs remain in memory, original text is streamed from SQLite.
    # Plan twice rather than retaining the original document text in memory.
    progress['stage_total'] = sum(1 for _ in leaf_plan(doc, budget, digest))
    for batch, cached in leaf_plan(doc, budget, digest):
        if cancel and cancel.is_set():
            raise InterruptedError('Préparation interrompue ; les lots terminés sont conservés.')
        if cached:
            completed(progress, cached=True)
            leaves.append(cached)
        else:
            leaves.append(await summarize_node(doc, batch, 2, model, digest, cancel, progress))
    if not leaves:
        raise llm.ModelError('Aucun texte exploitable à résumer.')
    progress['stage'] = 'chapitres'
    merge_budget = llm.evidence_budget(question, 'synthèse structurée, 120 mots maximum', 320, context=summary_context(3))
    for depth in range(12):
        groups = list(batches(leaves, merge_budget))
        progress.update(stage=f'regroupement {depth + 1}', stage_completed=0, stage_total=len(groups))
        if len(groups) == 1:
            progress['stage'] = 'synthèse globale'
            root = await summarize_node(doc, groups[0], 4, model, digest, cancel, progress)
            if cancel and cancel.is_set():
                raise InterruptedError('Préparation interrompue ; les lots terminés sont conservés.')
            # Point to a validated, completed summary; old per-batch caches remain
            # usable and gain this shortcut on their first successful traversal.
            with db() as c:
                for version in (PROMPT_VERSION, 'hierarchy-v6'):
                    for context in dict.fromkeys((summary_context(4), settings.context)):
                        key = summary_key(groups[0], 4, digest, version, context)
                        c.execute('''INSERT OR IGNORE INTO summary_roots
                                     SELECT ?,doc,key FROM summaries WHERE key=? AND doc=?''',
                                  (root_cache_key, key, doc))
            return root
        parents = []
        for batch in groups:
            parents.append(await summarize_node(doc, batch, 3, model, digest, cancel, progress))
        before = sum(llm.token_estimate(n['text']) for n in leaves)
        after = sum(llm.token_estimate(n['text']) for n in parents)
        if after >= before:
            raise llm.ModelError('Les résumés ne diminuent plus : arrêt pour éviter une boucle coûteuse.')
        leaves = parents
    raise llm.ModelError('Hiérarchie trop profonde : synthèse arrêtée sans perte silencieuse.')


async def answer(doc, question, model, strategy='auto', output_format='détaillé'):
    with llm.trace(doc):
        async with aclosing(_answer(doc, question, model, strategy, output_format)) as response:
            async for event in response:
                yield event


async def _answer(doc, question, model, strategy='auto', output_format='détaillé'):
    started = time.perf_counter()
    info = document(doc)
    digest = await llm.validate_model(model)
    chosen = route(question) if strategy == 'auto' else strategy
    if strategy == 'auto' and chosen == 'summary':
        chosen = 'fast'
    using_webnn = model in webnn.MODELS
    using_gguf = model == llamacpp.MODEL or model in wllama.DEVICES
    token_budgeted = using_webnn or using_gguf
    generation_format, response_tokens = answer_policy(output_format)
    generation_question = (question + '\n' + FAST_POLICY
                           if chosen == 'fast' and (not using_webnn or model == webnn.QWEN3) else question)
    browser = webnn.ACTIVE.get()
    device_key = ('webnn-device-v2', browser.device) if browser and using_webnn else ()
    cache_key = fingerprint('answer-v4', FAST_POLICY, selection.VERSION, summary.VERSION, llm.TRANSPORT_VERSION, llm.COMPACT_SYSTEM,
                            doc, digest, model, question, strategy, generation_format,
                            response_tokens, settings.context, settings.summary_context,
                            token_budget.method(model), root_key(doc, digest),
                            [(r['id'], r['text'], r['title'], r['section']) for r in chunks(doc)], *device_key)
    with db() as c:
        cached = c.execute('SELECT * FROM answer_cache WHERE key=? AND doc=?', (cache_key, doc)).fetchone()
    if cached:
        previous = json.loads(cached['metrics'])
        metrics = {'cached_answer': True, 'model_calls': 0, 'prompt_tokens': 0, 'output_tokens': 0,
                   'strategy': previous['strategy'], 'source_blocks': previous['source_blocks'],
                   'total_blocks': previous['total_blocks'],
                   **{key: previous[key] for key in ('runtime', 'device', 'model', 'gpu_layers', 'total_layers') if key in previous},
                   'total_ms': (time.perf_counter() - started) * 1000}
        if 'coverage' in previous:
            metrics['coverage'] = previous['coverage']
        source_rows = json.loads(cached['sources'])
        _save(doc, question, cached['answer'], source_rows, metrics)
        yield {'type': 'done', 'answer': cached['answer'], 'sources': source_rows, 'metrics': metrics,
               'warnings': json.loads(cached['warnings'])}
        return
    count = token_budget.counter(model) if token_budgeted else llm.token_estimate
    final_context = webnn.MODELS[model].context if using_webnn else (
        llamacpp.CONTEXT if using_gguf else settings.context)
    budget = (summary.budget(model, question, generation_format, response_tokens, final_context)
              if token_budgeted else llm.evidence_budget(question, generation_format, response_tokens))
    warnings, ids, evidence, summary_calls = [], [], '', 0
    coverage = None
    total_chunks = info['chunks']
    if info['warnings']:
        warnings.extend(info['warnings'][:10])
    if chosen == 'fast':
        yield {'type': 'status', 'text': 'Sélection extractive des sections du document, sans appel au modèle…'}
        if not token_budgeted:
            final_context = min(max(settings.context, settings.summary_context), 8192)
        budget = summary.budget(model, generation_question, generation_format, response_tokens, final_context)
        evidence, ids, coverage = selection.select(list(chunks(doc)), info['sections'], budget, token_budget.counter(model))
        warnings.append('Résumé rapide : sélection de passages, couverture partielle du texte. Les sections retenues ne sont pas une preuve d’exhaustivité. Utilisez le mode approfondi pour lire tous les blocs extraits.' if coverage['partial'] else
                        'Tous les blocs extraits tiennent dans le contexte ; le résumé peut néanmoins omettre des détails.')
    elif chosen == 'section':
        match = re.search(r'(chapitre|section|partie)\s+([\w.-]+)', normalize(question))
        target = ' '.join(match.groups()).rstrip('.-') if match else ''
        found = [s for s in info['sections'] if target and re.search(r'(?<!\w)' + re.escape(target) + r'(?!\w)', normalize(s['title']))]
        if not found:
            yield {'type': 'done', 'answer': 'Section introuvable dans le sommaire détecté. Choisissez son titre exact.', 'sources': [], 'metrics': {'strategy': chosen, 'model_calls': 0}, 'warnings': warnings}
            return
        rows = list(chunks(doc, found[0]['id']))
        evidence, ids = pack(rows, budget, count)
        if token_budgeted and len(ids) < len(rows):
            yield {'type': 'status', 'text': 'Synthèse de la section ciblée…'}
            progress = {'completed': 0, 'cached': 0, 'calls': 0}
            limit = summary.budget(model, summary.QUESTION, summary.FORMAT, 640, final_context)
            nodes = [{'text': source_text(row), 'ids': [row['id']]} for row in rows]
            level = 2
            while True:
                condensed = [await summary.node(doc, batch, level, model, digest, None, progress)
                             for batch in summary.groups(nodes, limit, count)]
                evidence = '\n\n'.join(node['text'] for node in condensed)
                if count(evidence) <= budget:
                    ids = sorted({i for node in condensed for i in node['ids']})
                    break
                if count(evidence) >= sum(count(node['text']) for node in nodes):
                    raise llm.ModelError('La section ne peut pas être condensée dans ce contexte.')
                nodes, level = condensed, 3
            summary_calls = progress['calls']
            warnings.append('Réponse fondée sur une synthèse complète de la section ; des détails peuvent être omis.')
        elif not token_budgeted and sum(count(source_text(r)) + 2 for r in rows) > budget:
            yield {'type': 'status', 'text': 'Synthèse de la section ciblée…'}
            progress = {'completed': 0, 'cached': 0, 'calls': 0}
            nodes = ({'text': source_text(r), 'ids': [r['id']]} for r in chunks(doc, found[0]['id']))
            leaves = []
            sq = SUMMARY_QUESTION
            for batch in batches(nodes, llm.evidence_budget(sq, 'synthèse structurée, 120 mots maximum', 320)):
                leaves.append(await summarize_node(doc, batch, 2, model, digest, None, progress))
            # Refuse partial section answers instead of silently dropping the tail.
            while sum(llm.token_estimate(n['text']) + 4 for n in leaves) > budget:
                previous = sum(llm.token_estimate(n['text']) for n in leaves)
                parents = []
                for batch in batches(leaves, llm.evidence_budget(sq, 'synthèse structurée, 120 mots maximum', 320)):
                    parents.append(await summarize_node(doc, batch, 3, model, digest, None, progress))
                if sum(llm.token_estimate(n['text']) for n in parents) >= previous:
                    raise llm.ModelError('La section ne peut pas être condensée dans ce contexte.')
                leaves = parents
            evidence = '\n\n'.join(n['text'] for n in leaves)
            ids = sorted({i for n in leaves for i in n['ids']})
            summary_calls = progress['calls']
            warnings.append('Réponse fondée sur une synthèse complète de la section ; des détails peuvent être omis.')
    elif chosen == 'direct' or (strategy == 'auto' and chosen in ['summary', 'hybrid'] and info['chars'] + total_chunks * 200 <= budget):
        evidence, ids = pack(chunks(doc), budget, count)
        if len(ids) < total_chunks:
            raise llm.ModelError('Lecture directe impossible dans ce contexte. Sélectionnez Synthèse ou Hybride.')
        chosen = 'direct'
    elif chosen in ['summary', 'hybrid']:
        yield {'type': 'status', 'text': 'Préparation des synthèses locales (les lots terminés seront réutilisés)…'}
        progress = {}
        task = asyncio.create_task(prepare(doc, model, digest, progress=progress))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=1)
                elapsed = round(time.perf_counter() - started)
                yield {'type': 'status', 'text': (
                    f"{progress.get('stage', 'Préparation')} : "
                    f"{progress.get('stage_completed', 0)}/{progress.get('stage_total', '?')} lots · "
                    f"{progress.get('cached', 0)} réutilisés · {elapsed // 60} min {elapsed % 60:02d} s. "
                    'Vous pouvez interrompre la préparation et reprendre avec les lots terminés.'),
                    'progress': dict(progress), 'elapsed_seconds': elapsed}
            root = task.result()
        finally:
            if not task.done():
                task.cancel()
            # Closing/aborting the HTTP stream must also close its Ollama request.
            await asyncio.gather(task, return_exceptions=True)
        evidence, ids = root['text'], root['ids']
        summary_calls = progress['calls']
        warnings.append('Synthèse couvrant tous les blocs extraits ; les détails peuvent être omis. Vérifiez les passages originaux.')
        warnings.append('La condensation hiérarchique peut perdre des réserves ou altérer une nuance. Les références sont contrôlées comme existantes, pas comme preuve de chaque affirmation.')
        read_rows = list(chunks(doc))
        read_sections = {r['section'] for r in read_rows if r['id'] in set(ids)}
        coverage = dict(partial=False, scope='all-extracted-blocks',
                        sections_selected=len(read_sections), sections_total=len(info['sections']),
                        sections=[dict(id=s['id'], title=s['title'], page=s['page'], selected=s['id'] in read_sections)
                                  for s in info['sections']],
                        pages_selected=sorted({r['page'] or r['block'] for r in read_rows if r['id'] in set(ids)}))
        if count(evidence) > budget:
            raise llm.ModelError('Synthèse trop longue pour cette question. Raccourcissez la question.')
        if chosen == 'hybrid':
            extra, extra_ids = pack(search(doc, question), budget - count(evidence) - 4, count)
            evidence += '\n\n' + extra
            ids = sorted(set(ids + extra_ids))
            if not extra_ids:
                warnings.append('Aucun passage BM25 supplémentaire ne tient dans le contexte.')
    else:
        evidence, ids = pack(search(doc, question), budget, count)
        warnings.append(f'Recherche ciblée : {len(ids)} passage(s) fourni(s) sur {total_chunks}. Une absence ici ne prouve pas une absence dans tout le document.')
    if not evidence.strip():
        result = 'Information introuvable dans les passages consultés. Aucun passage textuel suffisamment pertinent n’a été trouvé.'
        metrics = {'strategy': chosen, 'model_calls': 0, 'total_ms': (time.perf_counter() - started) * 1000}
        _save(doc, question, result, [], metrics)
        yield {'type': 'done', 'answer': result, 'sources': [], 'metrics': metrics, 'warnings': warnings}
        return
    # Only send citations and original snippets actually used/cited, not thousands of full pages.
    yield {'type': 'status', 'text': 'Rédaction de la réponse…'}
    preparation_ms = (time.perf_counter() - started) * 1000
    first_token_total_ms = None
    first_visible_total_ms = None
    result, metrics = '', {}
    structured_final = chosen in ('fast', 'summary', 'hybrid')
    final_schema = None
    if structured_final:
        paragraph_limit = 2 if response_tokens <= 256 else 4 if response_tokens <= 384 else 5
        final_words = 70 if response_tokens <= 256 else 100 if response_tokens <= 384 else 150
        allowed = sorted({int(v) for v in re.findall(r'\[S(\d+)\]', evidence)} & set(ids))
        final_schema = {'type': 'object', 'properties': {'paragraphs': {
            'type': 'array', 'minItems': 1, 'maxItems': paragraph_limit, 'items': {
                'type': 'object', 'properties': {'text': {'type': 'string'},
                    'source_ids': {'type': 'array', 'minItems': 1, 'maxItems': 3,
                                   'items': {'type': 'integer', 'enum': allowed}}},
                'required': ['text', 'source_ids'], 'additionalProperties': False}}},
            'required': ['paragraphs'], 'additionalProperties': False}
        if chosen == 'fast':
            item = final_schema['properties']['paragraphs']['items']
            item['properties'] = {'source_ids': item['properties']['source_ids'], 'text': item['properties']['text']}
        generation_format += f'. JSON paragraphs : text et source_ids pour chaque paragraphe, {final_words} mots au total maximum.'
    async for event in llm.generate(model, generation_question, evidence, generation_format, response_tokens, schema=final_schema, context=final_context):
        if event['type'] == 'token':
            if first_token_total_ms is None:
                first_token_total_ms = (time.perf_counter() - started) * 1000
            result += event['text']
            if not structured_final:
                if first_visible_total_ms is None:
                    first_visible_total_ms = (time.perf_counter() - started) * 1000
                yield event
        else:
            metrics = event['metrics']
    evidence_ids = sorted({int(v) for v in re.findall(r'\[S(\d+)\]', evidence)} & set(ids))
    if structured_final:
        try:
            if metrics.get('done_reason') == 'length':
                raise ValueError('limite de sortie atteinte')
            paragraphs = json.loads(result)['paragraphs']
            if not 1 <= len(paragraphs) <= 5:
                raise ValueError('paragraphes invalides')
            parts = []
            for paragraph in paragraphs:
                references = paragraph['source_ids']
                if not references or any(type(i) is not int or i not in evidence_ids for i in references):
                    raise ValueError('sources invalides')
                if not isinstance(paragraph['text'], str) or not paragraph['text'].strip():
                    raise ValueError('texte vide')
                parts.append(paragraph['text'] + ' ' + ' '.join(f'[S{i}]' for i in sorted(set(references))))
            result = '\n\n'.join(parts)
        except (ValueError, KeyError, TypeError) as exc:
            preview = webnn.extractive_preview(evidence, set(evidence_ids), paragraph_limit) if using_webnn and chosen == 'fast' else ''
            if not preview:
                message = ('Résumé final tronqué ; aucun résultat incomplet mis en cache. Choisissez un format plus court.'
                           if metrics.get('done_reason') == 'length' else
                           'Résumé final sans références valides ; résultat non enregistré.')
                raise llm.ModelError(message) from exc
            result = '**Extraits clés du document**\n\nLe modèle n’a pas produit de résumé avec des références valides. Voici des passages du texte original.\n\n' + preview
            metrics['extractive_fallback'] = True
        first_visible_total_ms = (time.perf_counter() - started) * 1000
        yield {'type': 'token', 'text': result}
    result, invalid = llm.validate_citations(result, evidence_ids)
    if not result.strip():
        raise llm.ModelError('Réponse vide retournée par le modèle local.')
    if invalid:
        warnings.append('Des références inventées ont été retirées de la réponse.')
    if metrics.get('done_reason') == 'length':
        warnings.append('Réponse interrompue par la limite de sortie ; elle peut être incomplète.')
    if any(c.get('thinking_chars') for c in llm.totals()['calls']):
        warnings.append('Ollama a émis du Thinking malgré think:false ; consultez les métriques de chaque appel.')
    cited = sorted({int(v) for v in re.findall(r'\[S(\d+)\]', result)})
    if not cited:
        warnings.append('Le modèle ne fournit aucune citation : réponse à vérifier.')
    source_rows = sources(cited or ids[:8])
    if coverage is not None:
        coverage['cited_pages'] = sorted({r['page'] or r['block'] for r in source_rows if r['id'] in cited})
        coverage['cited_sections'] = sorted({r['section'] for r in source_rows if r['id'] in cited})
    metrics.update(strategy=chosen, model_calls=1 + summary_calls,
                   preparation_ms=preparation_ms, time_to_first_token_ms=first_token_total_ms,
                   time_to_first_visible_token_ms=first_visible_total_ms,
                   total_ms=(time.perf_counter() - started) * 1000,
                   source_blocks=len(ids), total_blocks=total_chunks)
    aggregate = llm.totals()
    if aggregate['model_calls']:
        metrics['final_call'] = dict(metrics)
        metrics.update(aggregate)
    if coverage is not None:
        metrics['coverage'] = coverage
    _save(doc, question, result, source_rows, metrics)
    # A cache hit is reuse, not a new independent model opinion. Never reuse
    # truncated, uncited or invalidly cited output as a completed answer.
    if cited and not invalid and metrics.get('done_reason') == 'stop' and not metrics.get('extractive_fallback'):
        with db() as c:
            c.execute('INSERT OR REPLACE INTO answer_cache VALUES (?,?,?,?,?,?)',
                      (cache_key, doc, result, json.dumps(source_rows, ensure_ascii=False),
                       json.dumps(metrics), json.dumps(warnings, ensure_ascii=False)))
    yield {'type': 'done', 'answer': result, 'sources': source_rows, 'metrics': metrics, 'warnings': warnings}


def _save(doc, question, answer_text, source_rows, metrics):
    with db() as c:
        c.execute('INSERT INTO messages(doc,question,answer,sources,metrics) VALUES (?,?,?,?,?)',
                  (doc, question, answer_text, json.dumps(source_rows, ensure_ascii=False), json.dumps(metrics)))
