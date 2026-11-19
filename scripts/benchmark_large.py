"""Measure sampled peak RSS for 3000 simple, synthetic PDF pages; no LLM."""
import gc
import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path

import psutil

from app.config import settings
from app.extract import extract
from app.store import initialize
from scripts.fixtures import make_pdf


def main():
    with tempfile.TemporaryDirectory(prefix='clair-benchmark-') as folder:
        settings.data_dir=Path(folder)
        (settings.data_dir/'files').mkdir()
        initialize()
        path=Path(folder)/'3000pages.pdf'
        make_pdf(path,3000)
        gc.collect()
        process=psutil.Process()
        baseline=process.memory_info().rss
        samples=[baseline]
        stop=threading.Event()
        def sample():
            while not stop.wait(.02): samples.append(process.memory_info().rss)
        worker=threading.Thread(target=sample)
        worker.start()
        started=time.perf_counter()
        try:
            info,cached=extract(path,path.name,hashlib.sha256(path.read_bytes()).hexdigest())
        finally:
            stop.set()
            worker.join()
        result={'fixture':'3000 pages synthétiques simples, 4 textes répétés, un tableau',
                'pdf_bytes':path.stat().st_size,'pages':info['pages'],'chunks':info['chunks'],
                'extraction_ms':info['extraction_ms'],'wall_ms':(time.perf_counter()-started)*1000,
                'baseline_rss_mb':baseline/1024**2,'sampled_peak_rss_mb':max(samples)/1024**2,
                'sampled_growth_mb':(max(samples)-baseline)/1024**2,'sampling_interval_ms':20,
                'samples':len(samples),'llm_calls':0,'cached':cached}
    Path('docs/benchmark-large.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__': main()
