"""Run translateLocally's native-messaging protocol over local subprocess pipes."""
import asyncio
import json
import struct
import subprocess
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from time import perf_counter

from .config import settings


EXECUTABLE = 'translateLocally.exe'
RELEASE = '8e31cff'
MAX_RESPONSE = 1024 * 1024


@dataclass(frozen=True)
class Model:
    code: str
    source: str
    target: str
    digest: str

    @property
    def id(self):
        return f'{self.code}:bergamot'

    @property
    def directory(self):
        return settings.data_dir / 'bergamot' / self.code

    def installed(self):
        return binary().is_file() and all((self.directory / name).is_file() for name in (
            'model_info.json', 'config.intgemm8bitalpha.yml', 'model.intgemm.alphas.bin',
            'vocab.fren.spm', 'lex.s2t.bin',
        ))


def binary():
    return settings.data_dir / 'bergamot' / EXECUTABLE


MODELS = {m.id: m for m in (
    Model('fr-en-tiny', 'fr', 'en', 'dccea16d03c0a3897b4ce085db676ae4bb2777f7e2b1755c04c0f92efa894b01'),
    Model('en-fr-tiny', 'en', 'fr', '805d112122af03d0fe2769eacaaaf5a9eac2c4b97e862a5b2cf0eb95862a7efb'),
)}


class Session:
    def __init__(self, process):
        self.process = process
        self.serial = 0

    async def request(self, command, data):
        self.serial += 1
        message = json.dumps({'id': self.serial, 'command': command, 'data': data},
                             ensure_ascii=False).encode('utf-8')
        writer, reader = self.process.stdin, self.process.stdout
        try:
            async with asyncio.timeout(60):
                writer.write(struct.pack('<I', len(message)) + message)
                await writer.drain()
                while True:
                    size, = struct.unpack('<I', await reader.readexactly(4))
                    if size > MAX_RESPONSE:
                        raise ValueError('Réponse Bergamot trop volumineuse.')
                    reply = json.loads(await reader.readexactly(size))
                    if reply.get('id') == self.serial and 'success' in reply:
                        break
        except TimeoutError as exc:
            raise ValueError('Bergamot ne répond pas. Vous pouvez reprendre la traduction.') from exc
        except (ConnectionError, asyncio.IncompleteReadError, ValueError, AttributeError) as exc:
            raise ValueError('La communication avec Bergamot a été interrompue.') from exc
        if not reply['success']:
            raise ValueError('Bergamot ne peut pas traduire ce passage avec le modèle local.')
        return reply['data']

    async def translate(self, source, model_id):
        start = perf_counter()
        data = await self.request('Translate', {'model': model_id, 'text': source, 'html': False})
        return {'text': data['target']['text'], 'done_reason': 'stop', 'device': 'cpu',
                'runtime': 'bergamot', 'elapsed_ms': (perf_counter() - start) * 1000}


@asynccontextmanager
async def open_session(model):
    # Use a dedicated working directory containing only the installed translation models.
    # Explicit model IDs and ListModels without remote entries keep inference offline.
    launch = asyncio.create_task(asyncio.create_subprocess_exec(
        str(binary()), '-p', cwd=model.directory.parent,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    ))
    try:
        try:
            process = await asyncio.shield(launch)
        except OSError as exc:
            raise ValueError('Impossible de démarrer Bergamot. Relancez installer-traduction.bat.') from exc
        session = Session(process)
        models = await session.request('ListModels', {'includeRemote': False})
        model_id = next((entry['id'] for entry in models
                         if entry['local'] and entry['shortname'] == model.code), None)
        if not model_id:
            raise ValueError('Modèle Bergamot introuvable. Relancez installer-traduction.bat.')
        yield session, model_id
    finally:
        # If disconnected during startup, collect the child before releasing the compute lock.
        with suppress(OSError):
            process = await launch
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
            await process.communicate()
