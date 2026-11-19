import asyncio
import json
import re

import pytest
import httpx

from app import engine, llm, selection, summary, token_budget
from app.store import chunks, db


def test_extractive_budget_breadth_and_exact_source_spans():
    rows, sections = [], []
    for page in range(1, 13):
        sections.append(dict(id=page, title=f'Chapitre {page}', page=page))
        rows.append(dict(id=page, section=page, page=page, block=page, title=f'Chapitre {page}',
                         text=f'Le projet numéro {page} utilise un protocole particulier pour garantir la sécurité des données.'))
    count = lambda text: len(text.encode())
    evidence, ids, coverage = selection.select(rows, sections, 550, count)
    assert count(evidence) <= 550
    assert len(ids) < len(rows)
    assert 12 in coverage['pages_selected']
    assert min(coverage['pages_selected']) <= 3
    assert coverage['partial']
    assert set(ids) == {int(i) for i in re.findall(r'\[S(\d+)\]', evidence)}
    assert all(r['text'] in evidence for r in rows if r['id'] in ids)
    assert all(s['selected'] == (s['id'] in ids) for s in coverage['sections'])


def test_sentence_crossing_chunks_retains_both_ids():
    rows = [dict(id=1, section=1, page=1, block=1, title='Projet', text='Le projet protège les données sensibles'),
            dict(id=2, section=1, page=1, block=1, title='Projet', text='avec une sauvegarde locale quotidienne.')]
    full_size = len('\n\n'.join(engine.source_text(r) for r in rows))
    evidence, ids, _ = selection.select(rows, [dict(id=1, title='Projet', page=1)], full_size - 1, len)
    assert ids == [1, 2]
    assert 'sensibles\navec' in evidence


def test_fast_is_one_call_then_zero_and_coverage_survives_cache(imported, monkeypatch):
    calls = []
    async def validate(model):
        return 'digest'
    async def generate(model, question, evidence, *args, **kwargs):
        calls.append(evidence)
        assert engine.FAST_POLICY in question
        props = kwargs['schema']['properties']['paragraphs']['items']['properties']
        assert list(props) == ['source_ids', 'text']
        source = re.search(r'\[S\d+\]', evidence).group()
        yield dict(type='token', text=json.dumps(dict(paragraphs=[dict(text='Fait vérifié', source_ids=[int(source[2:-1])])])))
        yield dict(type='llm_metrics', metrics=dict(done_reason='stop'))
    monkeypatch.setattr(llm, 'validate_model', validate)
    monkeypatch.setattr(llm, 'generate', generate)
    async def run():
        first = [e async for e in engine.answer(imported['id'], 'Résume le document', 'fake', 'auto')][-1]
        assert first['metrics']['strategy'] == 'fast'
        assert first['metrics']['model_calls'] == 1
        assert first['metrics']['coverage']['scope'] == 'all-extracted-blocks'
        second = [e async for e in engine.answer(imported['id'], 'Résume le document', 'fake', 'auto')][-1]
        assert second['metrics']['model_calls'] == 0
        assert first['metrics']['coverage'] == second['metrics']['coverage']
        assert len(calls) == 1
    asyncio.run(run())


def test_fast_rejects_invented_structured_reference(imported, monkeypatch):
    async def validate(model):
        return 'digest'
    async def generate(*args, **kwargs):
        yield dict(type='token', text=json.dumps(dict(paragraphs=[dict(text='Fait.', source_ids=[999999])])) )
        yield dict(type='llm_metrics', metrics=dict(done_reason='stop'))
    monkeypatch.setattr(llm, 'validate_model', validate)
    monkeypatch.setattr(llm, 'generate', generate)
    async def run():
        with pytest.raises(llm.ModelError, match='références valides'):
            _ = [e async for e in engine.answer(imported['id'], 'Résumé ?', 'fake', 'fast')]
        with db() as c:
            assert c.execute('SELECT count(*) FROM answer_cache').fetchone()[0] == 0
    asyncio.run(run())


def test_token_hierarchy_resume_content_and_model_invalidation(imported, monkeypatch):
    # A small budget forces multiple real groups; fake model tests orchestration,
    # citation validation and caching only, never speed or factual quality.
    monkeypatch.setattr(summary, 'budget', lambda *args: 400)
    monkeypatch.setitem(token_budget.COUNTERS, 'fake', len)
    calls = []
    async def generate(model, question, evidence, *args, **kwargs):
        calls.append(evidence)
        ids = sorted({int(i) for i in re.findall(r'\[S(\d+)\]', evidence)})[:6]
        yield dict(type='token', text=json.dumps(dict(summary='Fait court.', source_ids=ids)))
        yield dict(type='llm_metrics', metrics=dict(done_reason='stop'))
    monkeypatch.setattr(llm, 'generate', generate)
    async def run():
        first = await summary.prepare(imported['id'], 'fake', 'digest')
        assert set(first['ids']) == {r['id'] for r in chunks(imported['id'])}
        before = len(calls)
        assert await summary.prepare(imported['id'], 'fake', 'digest') == first
        assert len(calls) == before
        await summary.prepare(imported['id'], 'fake', 'other-digest')
        assert len(calls) > before
    asyncio.run(run())


def test_unchanged_token_nodes_reused_when_neighbor_changes(imported, monkeypatch):
    monkeypatch.setitem(token_budget.COUNTERS, 'fake', len)
    rows = list(chunks(imported['id']))
    nodes = [dict(text=engine.source_text(r), ids=[r['id']]) for r in rows[:2]]
    calls = []
    async def generate(model, question, evidence, *args, **kwargs):
        calls.append(evidence)
        i = int(re.search(r'\[S(\d+)\]', evidence).group(1))
        yield dict(type='token', text=json.dumps(dict(summary='Fait.', source_ids=[i])))
        yield dict(type='llm_metrics', metrics=dict(done_reason='stop'))
    monkeypatch.setattr(llm, 'generate', generate)
    async def run():
        progress = dict(completed=0, cached=0, calls=0)
        for n in nodes:
            await summary.node(imported['id'], [n], 2, 'fake', 'digest', None, progress)
        nodes[1]['text'] += '\nFait modifié.'
        for n in nodes:
            await summary.node(imported['id'], [n], 2, 'fake', 'digest', None, progress)
        assert len(calls) == 3
        assert progress['cached'] == 1
    asyncio.run(run())


def test_native_totals_and_durable_call_log(imported):
    with llm.trace(imported['id']):
        for tokens, output in [(100, 10), (200, 20)]:
            llm.record(dict(prompt_tokens=tokens, output_tokens=output,
                            output_generation_ms=1000, generation_ms=2000), 'fake')
        totals = llm.totals()
        assert totals['model_calls'] == 2
        assert totals['prompt_tokens'] == 300
        assert totals['output_tokens'] == 30
        assert totals['tokens_per_second'] == 15
        # Updating the final call with aggregate fields must remain serializable.
        final = dict(llm.TRACE.get()['calls'][-1])
        final.update(totals)
        json.dumps(final)
        with db() as c:
            assert c.execute('SELECT count(*) FROM llm_calls WHERE run=?', (totals['run_id'],)).fetchone()[0] == 2
    assert llm.TRACE.get() is None


def test_native_stream_options_thinking_and_aggregate_snapshot(imported, monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body['think'] is False
        assert 'num_gpu' not in body['options']
        assert body['options']['num_ctx'] == 4096
        assert body['keep_alive'] == '10m'
        items = [dict(message=dict(content='Fait [S1].')),
                 dict(done=True, done_reason='stop', prompt_eval_count=123, eval_count=12,
                      eval_duration=2_000_000_000, load_duration=10_000_000,
                      prompt_eval_duration=1_000_000_000)]
        return httpx.Response(200, content='\n'.join(json.dumps(i) for i in items))
    monkeypatch.setattr(llm, 'client', lambda: httpx.AsyncClient(
        base_url='http://127.0.0.1', transport=httpx.MockTransport(handler)))
    async def run():
        with llm.trace(imported['id']):
            events = [e async for e in llm.generate('fake', 'Question ?', '[S1] Fait.', context=4096)]
            metrics = events[-1]['metrics']
            assert metrics['prompt_tokens'] == 123
            assert metrics['thinking_chars'] == 0
            assert metrics['tokens_per_second'] == 6
            metrics.update(llm.totals())
            json.dumps(metrics)
            assert metrics['model_calls'] == 1
    asyncio.run(run())
