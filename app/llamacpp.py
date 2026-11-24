"""Managed, CPU-only llama.cpp connection scoped to a document operation."""
import asyncio
import json
import secrets
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

import httpx

from .config import settings

MODEL = 'qwen3-4b:llamacpp'
NAME = 'Qwen3 4B'
CONTEXT = 3072
RELEASE = 'b12650'
MODEL_FILE = 'Qwen3-4B-Q4_K_M.gguf'
MODEL_SHA256 = '7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
MODEL_SIZE = 2497280256
ACTIVE = ContextVar('llamacpp_session', default=None)


def directory():
    return settings.data_dir / 'cpu-bench'


def executable():
    return directory() / RELEASE / 'llama-server.exe'


def installed():
    return executable().is_file() and weights_installed()


def weights_installed():
    try:
        return (directory() / MODEL_FILE).stat().st_size == MODEL_SIZE
    except OSError:
        return False


def chatml(messages):
    turns = [f"<|im_start|>{m['role']}\n{m['content'].replace('<|', '‹|')}<|im_end|>\n" for m in messages]
    return ''.join(turns) + '<|im_start|>assistant\n<think>\n\n</think>\n\n'


class Session:
    def __init__(self):
        self.process = None
        self.client = None

    async def start(self):
        if self.client is not None:
            return 0
        started = time.perf_counter()
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        key = secrets.token_urlsafe(32)
        args = [str(executable()), '-m', str(directory() / MODEL_FILE), '--host', '127.0.0.1',
                '--port', str(port), '--api-key', key, '-dev', 'none', '-ngl', '0', '-np', '1',
                '-c', str(CONTEXT), '-t', str(settings.threads), '-tb', str(settings.threads),
                '--no-ui', '--no-warmup', '--no-cache-prompt', '--no-context-shift', '--fit', 'off']
        with (directory() / 'llama-clair.log').open('wb') as log:
            self.process = subprocess.Popen(args, cwd=executable().parent, stdout=log,
                                            stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.client = httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}',
                                        headers={'Authorization': f'Bearer {key}'},
                                        timeout=240, trust_env=False)
        deadline = time.monotonic() + 120
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                if (await self.client.get('/health', timeout=1)).is_success:
                    return (time.perf_counter() - started) * 1000
            except httpx.TransportError:
                pass
            await asyncio.sleep(0.15)
        raise ValueError('llama.cpp ne démarre pas. Consultez data/cpu-bench/llama-clair.log.')

    async def close(self):
        if self.process is not None:
            self.process.kill()
            await asyncio.to_thread(self.process.wait, 10)
        if self.client is not None:
            await self.client.aclose()

    async def stream(self, messages, reserve, schema):
        start = time.perf_counter()
        load = await self.start()
        final = None
        first = None
        payload = {'prompt': chatml(messages), 'n_predict': reserve, 'stream': True,
                   'temperature': 0, 'repeat_penalty': 1.16, 'repeat_last_n': reserve,
                   'cache_prompt': False}
        if schema:
            payload['json_schema'] = schema
        async with self.client.stream('POST', '/completion', json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                data = line[6:]
                if data == '[DONE]':
                    break
                item = json.loads(data)
                if item.get('error'):
                    raise ValueError('llama.cpp a interrompu la génération.')
                if content := item.get('content'):
                    if first is None:
                        first = (time.perf_counter() - start) * 1000
                    yield {'type': 'token', 'text': content}
                if item.get('stop'):
                    final = item
                    break
        if final is None:
            raise ValueError('Le flux llama.cpp s’est interrompu avant la fin.')
        timing = final.get('timings', {})
        yield {'type': 'llm_metrics', 'metrics': {
            'runtime': 'llamacpp', 'model': MODEL, 'device': 'cpu', 'context': CONTEXT,
            'threads': settings.threads, 'load_ms': load, 'first_token_ms': first,
            'generation_ms': (time.perf_counter() - start) * 1000,
            'prompt_tokens': timing.get('prompt_n'), 'output_tokens': timing.get('predicted_n'),
            'prompt_evaluation_ms': timing.get('prompt_ms'), 'output_generation_ms': timing.get('predicted_ms'),
            'done_reason': 'length' if final.get('stop_type') == 'limit' else 'stop',
        }}


@asynccontextmanager
async def session():
    connection = Session()
    token = ACTIVE.set(connection)
    try:
        yield
    finally:
        ACTIVE.reset(token)
        await connection.close()
