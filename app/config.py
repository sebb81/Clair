import os
from dataclasses import dataclass
from pathlib import Path

import psutil


def default_summary_context():
    ram = psutil.virtual_memory()
    return 16384 if ram.total >= 32 * 1024**3 and ram.available >= 16 * 1024**3 else 4096


@dataclass
class Settings:
    data_dir: Path = Path(os.environ.get('LOCALDOC_DATA', 'data')).resolve()
    ollama_url: str = 'http://127.0.0.1:11434'
    ollama_cpu: bool = os.environ.get('LOCALDOC_OLLAMA_CPU') == '1'
    max_upload_mb: int = int(os.environ.get('LOCALDOC_MAX_UPLOAD_MB', '100'))
    max_text_mb: int = int(os.environ.get('LOCALDOC_MAX_TEXT_MB', '80'))
    context: int = int(os.environ.get('LOCALDOC_CONTEXT', '4096'))
    summary_context: int = int(os.environ.get('LOCALDOC_SUMMARY_CONTEXT', str(default_summary_context())))
    answer_tokens: int = 640
    keep_alive: str = os.environ.get('LOCALDOC_KEEP_ALIVE', '10m')
    threads: int = min(8, psutil.cpu_count(logical=False) or 2)

    def __post_init__(self):
        if not 2048 <= self.context <= 32768:
            raise ValueError('LOCALDOC_CONTEXT doit être compris entre 2048 et 32768.')
        if not 4096 <= self.summary_context <= 32768:
            raise ValueError('LOCALDOC_SUMMARY_CONTEXT doit être compris entre 4096 et 32768.')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / 'files').mkdir(exist_ok=True)


settings = Settings()
