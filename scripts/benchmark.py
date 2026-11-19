"""Real Ollama/CPU benchmark. No fake provider and no model downloads.

Run: .venv\Scripts\python.exe -m scripts.benchmark
The local server must already be listening on port 8765.
"""
import asyncio
import json
import platform
import os
import time
from pathlib import Path

import httpx
import psutil


async def main():
    results = {'date': '2026-11-16', 'platform': platform.platform(),
               'ram_total_mb': round(psutil.virtual_memory().total/1024**2),
               'model':os.environ.get('BENCHMARK_MODEL', 'qwen3.5:2b'), 'runs':[]}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8765',trust_env=False,timeout=600) as c:
        path=Path('tests/fixtures/horizon.pdf')
        r=await c.post('/api/documents',files={'file':(path.name,path.read_bytes(),'application/pdf')})
        r.raise_for_status()
        results['import']=r.json()
        doc=r.json()['document']['id']
        cases=[('direct','Résume le document : objectif, budget, risques et décisions.'),
               ('summary','Résume le document : objectif, budget, risques et décisions.'),
               ('hybrid','Quel est le budget annoncé pour 2027 ? Quels risques peuvent affecter le projet ?'),
               ('bm25','Quel est le budget annoncé pour 2027 ?'),
               ('auto','Qui est la responsable du projet ?'),
               ('auto','Quel est le taux de TVA ?'),
               ('auto','Quel est le budget pour 2099 ?'),
               ('auto','Résume le chapitre 3.'),
               ('summary','Résume le document : objectif, budget, risques et décisions.')]
        for strategy,question in cases:
            started=time.perf_counter()
            run={'strategy_requested':strategy,'question':question}
            try:
                async with c.stream('POST',f'/api/documents/{doc}/ask',json={
                    'question':question,'model':results['model'],'strategy':strategy,'output_format':'réponse courte'}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line: continue
                        event=json.loads(line)
                        if event['type']=='done': run.update(event)
                        elif event['type']=='error': run['error']=event['message']
                run['client_total_ms']=(time.perf_counter()-started)*1000
                results['runs'].append(run)
                print(json.dumps({k:v for k,v in run.items() if k not in ['sources']},ensure_ascii=True),flush=True)
            except Exception as exc:
                run['error']=str(exc)
                results['runs'].append(run)
            results['health_after_run']= (await c.get('/api/health')).json()
            tag=results['model'].replace(':','-').replace('/','-')
            target=Path('docs')/f'benchmark-{tag}.json'
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Evidence written to {target}',flush=True)


if __name__=='__main__': asyncio.run(main())
