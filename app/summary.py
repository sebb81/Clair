"""Token-budgeted hierarchy; the legacy checkpoint reader stays in engine.py."""
import json
import re

from . import llamacpp, llm, token_budget, webnn
from .config import settings
from .store import chunks, db

VERSION = 'hierarchy-token-v1'
QUESTION = ('Condense les faits explicites en 70 mots maximum. Préserve noms, chiffres, décisions et risques. '
            'Ne conclus jamais à une absence. JSON : summary et source_ids, au plus 6 sources représentatives.')
FORMAT = 'JSON complet, résumé factuel court et sources utilisées.'


def context():
    if browser := webnn.ACTIVE.get():
        return browser.context
    if llamacpp.ACTIVE.get() is not None:
        return llamacpp.CONTEXT
    return max(settings.context, settings.summary_context)


def budget(model, question, output_format, reserve, ctx):
    count = token_budget.counter(model)
    overhead = sum(count(m['content']) for m in llm.compact_prompt(question, '', output_format))
    return max(0, ctx - reserve - overhead - 256)


def groups(nodes, limit, count):
    group, used = [], 0
    for node in nodes:
        cost = count(node['text']) + 8
        if cost > limit:
            raise llm.ModelError('Un passage dépasse le budget de tokens de la synthèse.')
        if group and used + cost > limit:
            yield group
            group, used = [], 0
        group.append(node)
        used += cost
    if group:
        yield group


def key(nodes, level, digest):
    from .engine import fingerprint
    return fingerprint(VERSION, llm.COMPACT_SYSTEM, QUESTION, FORMAT, digest,
                       context(), settings.threads, level,
                       640 if level == 4 else 384, nodes)


async def node(doc, nodes, level, model, digest, cancel, progress):
    from .engine import completed
    if cancel and cancel.is_set():
        raise InterruptedError('Préparation interrompue ; les lots terminés sont conservés.')
    cache_key = key(nodes, level, digest)
    ids = sorted({i for n in nodes for i in n['ids']})
    with db() as c:
        cached = c.execute('SELECT text FROM summaries WHERE key=? AND doc=?', (cache_key, doc)).fetchone()
    if cached:
        completed(progress, cached=True)
        return dict(text=cached['text'], ids=ids)
    evidence = '\n\n'.join(n['text'] for n in nodes)
    allowed = sorted({int(i) for i in re.findall(r'\[S(\d+)\]', evidence)} & set(ids))
    schema = {'type': 'object', 'properties': {'summary': {'type': 'string'},
              'source_ids': {'type': 'array', 'items': {'type': 'integer', 'enum': allowed},
                             'minItems': 1, 'maxItems': 6}},
              'required': ['summary', 'source_ids'], 'additionalProperties': False}
    duration = 0
    for attempt in range(2):
        question = QUESTION if level != 4 else QUESTION.replace('70 mots', '160 mots')
        if attempt:
            question = QUESTION.replace('70 mots', '40 mots')
        text, metrics = '', {}
        progress['calls'] += 1
        progress['retries'] = progress.get('retries', 0) + int(attempt > 0)
        async for event in llm.generate(model, question, evidence, FORMAT,
                640 if level == 4 else 384, schema=schema, context=context()):
            if cancel and cancel.is_set():
                raise InterruptedError('Préparation interrompue ; reprise possible.')
            if event['type'] == 'token':
                text += event['text']
            else:
                metrics = event['metrics']
        duration += metrics.get('generation_ms', 0)
        if metrics.get('done_reason') != 'length':
            break
    else:
        raise llm.ModelError('Lot tronqué après deux tentatives ; aucun cache incomplet enregistré.')
    try:
        structured = json.loads(text)
        cited = structured['source_ids']
        if not cited or any(type(i) is not int or i not in allowed for i in cited):
            raise ValueError('sources invalides')
        body, invalid = llm.validate_citations(structured['summary'], allowed)
        if not body.strip() or invalid:
            raise ValueError('texte invalide')
        body += '\nSources : ' + ' '.join(f'[S{i}]' for i in sorted(set(cited)))
    except (ValueError, KeyError, TypeError) as exc:
        raise llm.ModelError('Résumé sans faits ou références valides, non enregistré.') from exc
    with db() as c:
        c.execute('INSERT OR IGNORE INTO summaries VALUES (?,?,?,?,?,?,?)',
                  (cache_key, doc, level, body, json.dumps(ids), model, duration))
    completed(progress)
    return dict(text=body, ids=ids)


async def prepare(doc, model, digest, cancel=None, progress=None):
    from . import engine
    progress = progress if progress is not None else {}
    progress.update(completed=0, cached=0, calls=0, stage='lecture par budget de tokens', stage_completed=0)
    if cancel and cancel.is_set():
        raise InterruptedError('Préparation interrompue ; reprise possible.')
    root_key = engine.fingerprint(VERSION, doc, digest, context(), settings.threads, QUESTION, llm.COMPACT_SYSTEM)
    with db() as c:
        cached = c.execute('SELECT s.text,s.sources FROM summary_roots r JOIN summaries s ON s.key=r.summary_key WHERE r.key=? AND r.doc=?',
                           (root_key, doc)).fetchone()
    if cached:
        progress.update(stage='synthèse globale', stage_total=1)
        engine.completed(progress, cached=True)
        return dict(text=cached['text'], ids=json.loads(cached['sources']))
    count = token_budget.counter(model)
    limit = budget(model, QUESTION, FORMAT, 768, context())
    # Reuse ALL completed legacy leaves when available; do not throw away the
    # user's already paid-for reading work just because grouping improved.
    old_limit = llm.evidence_budget(engine.SUMMARY_QUESTION, 'synthèse structurée, 120 mots maximum', 320)
    old_plan = (list(engine.leaf_plan(doc, old_limit, digest)) if webnn.ACTIVE.get() is None and model != llamacpp.MODEL else
                [([{'text': engine.source_text(row), 'ids': [row['id']]}], None) for row in chunks(doc)])
    plan, pending = [], []
    for old_nodes, cached in old_plan:
        if cached:
            plan.extend((batch, None) for batch in groups(pending, limit, count))
            pending = []
            plan.append((old_nodes, cached))
        else:
            pending.extend(old_nodes)
    plan.extend((batch, None) for batch in groups(pending, limit, count))
    progress['stage_total'] = len(plan)
    leaves = []
    for batch, cached in plan:
        if cancel and cancel.is_set():
            raise InterruptedError('Préparation interrompue ; reprise possible.')
        if cached:
            engine.completed(progress, cached=True)
            leaves.append(cached)
        else:
            leaves.append(await node(doc, batch, 2, model, digest, cancel, progress))
    if not leaves:
        raise llm.ModelError('Aucun texte exploitable à résumer.')
    for depth in range(12):
        plan = list(groups(leaves, limit, count))
        progress.update(stage=f'regroupement {depth + 1}', stage_completed=0, stage_total=len(plan))
        if len(plan) == 1:
            result = await node(doc, plan[0], 4, model, digest, cancel, progress)
            with db() as c:
                c.execute('INSERT OR IGNORE INTO summary_roots VALUES (?,?,?)', (root_key, doc, key(plan[0], 4, digest)))
            return result
        parents = []
        for batch in plan:
            parents.append(await node(doc, batch, 3, model, digest, cancel, progress))
        if sum(count(n['text']) for n in parents) >= sum(count(n['text']) for n in leaves):
            raise llm.ModelError('Condensation insuffisante : arrêt de la hiérarchie.')
        leaves = parents
    raise llm.ModelError('Hiérarchie trop profonde.')
