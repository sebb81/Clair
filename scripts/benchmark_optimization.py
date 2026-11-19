"""Compare the former short-answer policy, the new policy and exact reuse.

Uses installed local weights and an isolated fixture database under data/.
Does not change the user's documents or call a cloud service.
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app import engine, llm
from app.config import settings
from app.extract import extract
from app.store import initialize


async def main():
    settings.ollama_cpu = True
    target = Path('docs/benchmark-optimization.json')
    report = {'date': datetime.now(timezone.utc).isoformat(), 'model': 'qwen3.5:9b',
              'device': 'cpu', 'runs': [], 'isolated_fixture': 'horizon.pdf'}
    original_data, policy = settings.data_dir, engine.answer_policy
    with TemporaryDirectory(prefix='optimization-', dir='data') as directory:
        try:
            settings.data_dir = Path(directory).resolve()
            (settings.data_dir / 'files').mkdir()
            initialize()
            info, _ = extract(Path('tests/fixtures/horizon.pdf'), 'horizon.pdf', 'benchmark')
            # Load the same model first. The comparison below is warm-model work;
            # it is not a benchmark of cold startup or a large-document summary.
            async for _ in llm.generate(report['model'], 'Réponds OK.', '[S1] Test.',
                                        'un mot', response_tokens=8):
                pass
            for label in ('previous_short_policy', 'bounded_short_policy', 'exact_repeat'):
                engine.answer_policy = (lambda output_format: (output_format, settings.answer_tokens)) if label == 'previous_short_policy' else policy
                started = time.perf_counter()
                result = None
                async for event in engine.answer(info['id'],
                        'Résume le document : objectif, budget, risques et décisions.',
                        report['model'], 'direct', 'réponse courte'):
                    if event['type'] == 'done':
                        result = event
                assert result and result['sources']
                report['runs'].append({'label': label, 'client_ms': (time.perf_counter() - started) * 1000,
                                       'answer': result['answer'], 'metrics': result['metrics'],
                                       'warnings': result['warnings']})
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report['runs'][-1], ensure_ascii=True), flush=True)
            assert report['runs'][-1]['metrics'].get('cached_answer')
            assert report['runs'][1]['answer'] == report['runs'][2]['answer']
        finally:
            settings.data_dir, engine.answer_policy = original_data, policy


if __name__ == '__main__':
    asyncio.run(main())
