"""Real CPU comparison on the same imported PDF, using isolated database copies.

python -m scripts.benchmark_summary_modes DOCUMENT_ID [--model qwen3.5:9b]
Progress: data/summary-benchmark-progress.json. Results: docs/benchmark-summary-modes.json.
Original documents, summaries and history are never changed by the benchmark.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import time
import uuid

import psutil

from app import engine, llm, summary, token_budget
from app.config import settings
from app.store import chunks, db, document, initialize


async def heartbeat(state, started, path):
    while True:
        state['elapsed_seconds'] = round(time.perf_counter() - started, 2)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
        await asyncio.sleep(2)


async def main():
    settings.ollama_cpu = True
    parser = argparse.ArgumentParser()
    parser.add_argument('document')
    parser.add_argument('--model', default='qwen3.5:9b')
    parser.add_argument('--strategies', nargs='+', choices=['fast', 'summary'], default=['fast', 'summary'])
    parser.add_argument('--append', action='store_true')
    args = parser.parse_args()
    original_data = settings.data_dir
    target = Path('docs/benchmark-summary-modes.json')
    progress_path = original_data / 'summary-benchmark-progress.json'
    info = document(args.document)
    with db() as c:
        original = dict(c.execute('SELECT path FROM documents WHERE id=?', (args.document,)).fetchone())
        historical = [dict(r) for r in c.execute('SELECT level,count(*) completed_nodes,sum(duration_ms) recorded_ms FROM summaries WHERE doc=? GROUP BY level', (args.document,))]
    digest = await llm.validate_model(args.model)
    count = token_budget.counter(args.model)
    rows = list(chunks(args.document))
    old_budget = llm.evidence_budget(engine.SUMMARY_QUESTION, 'synthèse structurée, 120 mots maximum', 320)
    report = dict(date=datetime.now(timezone.utc).isoformat(), document=info,
                  pdf_sha256=hashlib.sha256(Path(original['path']).read_bytes()).hexdigest(),
                  model=args.model, digest=digest, model_info=llm.MODEL_INFO[args.model],
                  cpu=os.environ.get('PROCESSOR_IDENTIFIER', platform.processor()),
                  ram_total=psutil.virtual_memory().total, threads=settings.threads,
                  contexts=dict(questions=settings.context, fast=min(summary.context(), 8192), deep=summary.context()),
                  budget_method=token_budget.method(args.model),
                  original_text_tokens=sum(count(r['text']) for r in rows),
                  legacy_leaf_batches=len(list(engine.legacy_leaf_groups(args.document, old_budget))),
                  legacy_fresh_leaf_batches=len(list(engine.leaf_plan(args.document, old_budget, 'empty-cache'))),
                  historical_nodes=historical, runs=[],
                  limits=['Single run per mode; model unloaded then preloaded with a tiny prompt before each mode.',
                          'Existing PDF extraction reused in both modes; extraction_ms reported separately.',
                          'Native tokens of historical runs were not retained and cannot be reconstructed.',
                          'Development machine, not a measurement on the target Dell.',
                          'Coverage reports input passages, not semantic completeness.'])
    folder = original_data / ('summary-benchmark-' + uuid.uuid4().hex[:10])
    folder.mkdir()
    if args.append:
        previous = json.loads(target.read_text(encoding='utf-8'))
        if previous['digest'] != digest or previous['pdf_sha256'] != report['pdf_sha256']:
            raise ValueError('Cannot combine measurements of different PDFs or weights')
        superseded = [r for r in previous['runs'] if r['strategy'] in args.strategies]
        previous.setdefault('superseded_runs', []).extend(superseded)
        previous['runs'] = [r for r in previous['runs'] if r['strategy'] not in args.strategies]
        report = previous
    for strategy in args.strategies:
        run_dir = folder / strategy
        run_dir.mkdir()
        source = sqlite3.connect(original_data / 'documents.sqlite')
        destination = sqlite3.connect(run_dir / 'documents.sqlite')
        source.backup(destination)
        destination.close()
        source.close()
        settings.data_dir = run_dir
        initialize()
        with db() as c:
            c.execute('DELETE FROM answer_cache')
            c.execute('DELETE FROM summary_roots')
            c.execute('DELETE FROM summaries')
            c.execute('DELETE FROM messages')
            c.execute('DELETE FROM llm_calls')
        try:
            for cached in (False, True):
                state = dict(strategy=strategy, cached=cached, status='running', directory=str(run_dir))
                progress_path.write_text(json.dumps(state, indent=2), encoding='utf-8')
                if not cached:
                    # Same warm-weight convention for each mode. Native load times
                    # of measured calls remain in the report. No cloud service.
                    async with llm.client(60) as c:
                        unloaded = await c.post('/api/generate', json={'model': args.model, 'keep_alive': 0})
                        unloaded.raise_for_status()
                    async for warm_event in llm.generate(args.model, 'Réponds OK.', '[S1] Test.', 'Un mot', 8,
                            context=report['contexts']['fast' if strategy == 'fast' else 'deep']):
                        if warm_event['type'] == 'llm_metrics':
                            report.setdefault('warmup', {})[strategy] = warm_event['metrics']
                started = time.perf_counter()
                result = None
                pulse = asyncio.create_task(heartbeat(state, started, progress_path))
                try:
                    async for event in engine.answer(args.document, 'Fais-moi un résumé structuré de ce document.',
                            args.model, strategy, 'résumé structuré'):
                        if event['type'] == 'status':
                            state.update(event=event, elapsed_seconds=round(time.perf_counter() - started, 2))
                            progress_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
                        elif event['type'] == 'done':
                            result = event
                finally:
                    pulse.cancel()
                    await asyncio.gather(pulse, return_exceptions=True)
                if not result:
                    raise RuntimeError('Missing completed answer')
                report['runs'].append(dict(strategy=strategy, cache_repeat=cached,
                    wall_ms=(time.perf_counter() - started) * 1000, result=result))
                async with llm.client(5) as c:
                    report['runs'][-1]['runtime'] = (await c.get('/api/ps')).json()
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(dict(strategy=strategy, cached=cached,
                    wall_ms=report['runs'][-1]['wall_ms'], calls=result['metrics']['model_calls'],
                    prompt_tokens=result['metrics'].get('prompt_tokens'), output_tokens=result['metrics'].get('output_tokens')), ensure_ascii=True), flush=True)
        except Exception as exc:
            report['error'] = dict(strategy=strategy, message=str(exc))
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            raise
        finally:
            settings.data_dir = original_data
    progress_path.write_text(json.dumps(dict(status='complete', report=str(target), directory=str(folder)), indent=2), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
