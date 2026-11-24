"""Compare Clair's WebNN worker and llama.cpp on identical documentary prompts."""
import argparse
import ctypes
import hashlib
import json
import os
import platform
import socket
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import httpx
import psutil

from app import llamacpp, llm, webnn

ROOT = Path(__file__).resolve().parents[1]
RELEASE = llamacpp.RELEASE
ARCHIVE = f'llama-{RELEASE}-bin-win-cpu-x64.zip'
MODEL_FILE = llamacpp.MODEL_FILE
MODEL_REVISION = 'bc640142c66e1fdd12af0bd68f40445458f3869b'
CONTEXT = llamacpp.CONTEXT
MIB = 1024**2
HIDE_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
EVIDENCE = """[S1] Le projet Horizon modernise les archives municipales. Nadia Martin pilote le projet.
[S2] Pour 2027, le budget total est de 240 000 euros, dont 90 000 pour l'équipement,
50 000 pour la formation et 100 000 pour la numérisation.
[S3] Le pilote commence en mars 2027. Le déploiement est prévu en septembre 2027.
[S4] Le prestataire reste à sélectionner. Aucun budget pour 2028 n'est indiqué."""


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def download(path, url, expected):
    def matches(candidate):
        with candidate.open('rb') as source:
            return hashlib.file_digest(source, 'sha256').hexdigest() == expected

    if path.is_file() and matches(path):
        return
    print(f'Téléchargement de {path.name}', flush=True)
    partial = path.with_suffix(path.suffix + '.part')
    if not partial.is_file() or not matches(partial):
        subprocess.run(['curl.exe', '--fail', '--silent', '--show-error', '--location',
                        '--retry', '2', '--connect-timeout', '15', '--continue-at', '-',
                        '--output', str(partial), url], check=True, timeout=1200)
    if not matches(partial):
        partial.unlink()
        raise ValueError(f'SHA-256 incorrect pour {path.name}. Relancez le téléchargement.')
    partial.replace(path)


def gguf(cache):
    model = cache / MODEL_FILE
    download(model, f'https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/{MODEL_REVISION}/{MODEL_FILE}',
             llamacpp.MODEL_SHA256)
    return model


def runtime(cache):
    binary_dir = cache / RELEASE
    archive = cache / ARCHIVE
    download(archive, f'https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{ARCHIVE}',
             '98ddbb60ab72c2b5c32fb66c17f4cb1fbc4b7f077aa8f1dee9fe9b941537f74d')
    if not all((binary_dir / file).is_file() for file in ('llama-bench.exe', 'llama-server.exe')):
        with ZipFile(archive) as bundle:
            bundle.extractall(binary_dir)
    return binary_dir, gguf(cache)


def machine():
    feature = ctypes.windll.kernel32.IsProcessorFeaturePresent
    feature.argtypes, feature.restype = [ctypes.c_uint32], ctypes.c_int
    try:
        details = subprocess.run(['powershell.exe', '-NoProfile', '-Command', '(Get-CimInstance Win32_Processor).Name'],
                                 capture_output=True, text=True, timeout=15)
        cpu = details.stdout.strip() or platform.processor()
    except subprocess.TimeoutExpired:
        cpu = platform.processor()
    return {'cpu': cpu, 'physical_cores': psutil.cpu_count(logical=False),
            'logical_cores': psutil.cpu_count(), 'ram_mib': round(psutil.virtual_memory().total / MIB),
            'windows': platform.version(), 'avx2': bool(feature(40)), 'avx512f': bool(feature(41))}


def cases():
    questions = (
        ('question', 'Quel est le budget total du projet Horizon et pour quelle année ?',
         'Une seule phrase avec la source exacte', 48),
        ('resume', 'Résume le budget 2027, les étapes du calendrier et le statut du prestataire.',
         'Trois puces brèves, une par sujet avec sa source exacte', 160),
    )
    return [{'id': name, 'request': {'messages': llm.compact_prompt(question, EVIDENCE, format),
                                     'max_tokens': limit, 'json_output': False}}
            for name, question, format, limit in questions]


def sweep(binary, model, output):
    print('Mesure des threads avec llama-bench (2, 4 et 8)', flush=True)
    with (output / 'threads.log').open('wb') as log:
        result = subprocess.check_output(
            [str(binary / 'llama-bench.exe'), '-m', str(model), '-dev', 'none', '-ngl', '0',
             '-p', '512', '-n', '64', '-t', '2,4,8', '-r', '3', '-o', 'json'],
            stderr=log, timeout=900)
    return json.loads(result)


def measure_memory(pid, stop, peaks):
    process = psutil.Process(pid)
    while not stop.is_set():
        try:
            info = process.memory_info()
        except psutil.NoSuchProcess:
            return
        for field, value in [('resident_peak_mib', info.rss), ('private_peak_mib', info.private)]:
            peaks[field] = max(peaks.get(field, 0), value / MIB)
        stop.wait(0.05)


def wait_for_server(process, client):
    deadline = time.monotonic() + 180
    while process.poll() is None and time.monotonic() < deadline:
        try:
            if client.get('/health', timeout=1).is_success:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.15)
    raise RuntimeError('llama-server ne répond pas. Consultez llama-server.log.')


def compare_llama(binary, model, output, requests, threads, batch_threads):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    params = ['-m', str(model), '--host', '127.0.0.1', '--port', str(port), '-c', str(CONTEXT),
              '-dev', 'none', '-ngl', '0', '-np', '1', '-t', str(threads), '-tb', str(batch_threads),
              '--no-warmup', '--no-webui', '--no-cache-prompt']
    results = []
    peaks = {}
    stop = threading.Event()
    started = time.perf_counter()
    log_path = output / 'llama-server.log'
    with log_path.open('wb') as log:
        process = subprocess.Popen([str(binary / 'llama-server.exe'), *params], stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=HIDE_WINDOW)
        sampler = threading.Thread(target=measure_memory, args=(process.pid, stop, peaks), daemon=True)
        sampler.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=240, trust_env=False) as client:
                wait_for_server(process, client)
                server_load_ms = (time.perf_counter() - started) * 1000
                for case in requests:
                    print(f"llama.cpp · {case['id']}", flush=True)
                    request = case['request']
                    start = time.perf_counter()
                    response = client.post('/completion', json={
                        'prompt': llamacpp.chatml(request['messages']), 'n_predict': request['max_tokens'],
                        'cache_prompt': False, 'temperature': 0, 'repeat_penalty': 1.16,
                        'repeat_last_n': request['max_tokens'], 'return_tokens': False,
                    })
                    response.raise_for_status()
                    elapsed = (time.perf_counter() - start) * 1000
                    raw = response.json()
                    timing = raw['timings']
                    results.append({'test': case['id'], 'elapsed_ms': elapsed, 'text': raw['content'],
                                    'prompt_tokens': timing['prompt_n'], 'output_tokens': timing['predicted_n'],
                                    'prompt_evaluation_ms': timing['prompt_ms'],
                                    'output_generation_ms': timing['predicted_ms'],
                                    'done_reason': 'length' if raw.get('stopped_limit') else raw.get('stop_type'),
                                    'cache_tokens': timing.get('cache_n')})
        finally:
            stop.set()
            sampler.join()
            process.kill()
            process.wait(timeout=10)
    return {'runtime': RELEASE, 'threads': threads, 'batch_threads': batch_threads,
            'context': CONTEXT, 'server_load_ms': server_load_ms, 'results': results, **peaks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    install = parser.add_mutually_exclusive_group()
    install.add_argument('--install-only', action='store_true', help='Installer le moteur natif sans lancer de benchmark.')
    install.add_argument('--install-gguf', action='store_true', help='Installer seulement le modèle de Wllama.')
    args = parser.parse_args()
    if platform.system() != 'Windows' or platform.machine().lower() not in ('amd64', 'x86_64'):
        parser.error('Ce banc utilise le binaire Windows x64.')
    cache = llamacpp.directory()
    if args.install_only or args.install_gguf:
        cache.mkdir(parents=True, exist_ok=True)
        if args.install_gguf:
            gguf(cache)
        else:
            runtime(cache)
        print('Qwen3 4B GGUF est installé. Rechargez Clair.')
        return
    spec = webnn.MODELS[webnn.QWEN3]
    if not spec.installed() or not (ROOT / 'web' / 'dist' / 'index.html').exists():
        parser.error('Installez Qwen3 4B WebNN et construisez Clair avant de lancer le banc.')
    output = cache / datetime.now().strftime('run-%Y%m%d-%H%M%S-%f')
    output.mkdir(parents=True)
    print(f'Résultats : {output}', flush=True)
    write_json(output / 'machine.json', machine())
    requests = cases()
    write_json(output / 'cases.json', requests)
    write_json(output / 'model.json', {'profile': spec.profile, 'directory': str(spec.asset('model.onnx').parent)})
    binary, model = runtime(cache)
    measurements = sweep(binary, model, output)
    write_json(output / 'threads.json', measurements)
    threads = max((row for row in measurements if row['n_gen']), key=lambda row: row['avg_ts'])['n_threads']
    batch = max((row for row in measurements if row['n_prompt'] == 512), key=lambda row: row['avg_ts'])['n_threads']
    print(f'Threads retenus sur ce poste : génération {threads}, prompt {batch}', flush=True)
    native = compare_llama(binary, model, output, requests, threads, batch)
    write_json(output / 'llama.json', native)
    env = {**os.environ, 'CLAIR_CPU_COMPARISON_DIR': str(output), 'CLAIR_BENCH_DEVICE': 'cpu',
           'CLAIR_BENCH_CONTEXT': str(CONTEXT), 'CLAIR_BENCH_TAG': 'cpu'}
    env.pop('CLAIR_BENCH_CASE', None)
    subprocess.run(['node', 'scripts/benchmark-webnn.mjs', 'qwen3-4b'], check=True, cwd=ROOT / 'web',
                   env=env, timeout=600)
    report = json.loads((output / 'qwen3-4b-cpu.json').read_text(encoding='utf-8'))
    if len(report['results']) != len(requests) or any(r.get('error') or r['external'] for r in report['results']):
        raise RuntimeError(f'Essai WebNN incomplet ou accès externe détecté. Consultez {output}.')
    for label, results in [('llama.cpp', native['results']), ('WebNN', report['results'])]:
        for index, result in enumerate(results):
            load = result.get('load_ms', 0)
            elapsed = result['elapsed_ms']
            if label == 'llama.cpp' and index == 0:
                load = native['server_load_ms']
                elapsed += load
            print(f"{label:10} {result['test']:8}  "
                  f"chargement {load/1000:6.2f} s  "
                  f"prompt {result['prompt_evaluation_ms']/1000:6.2f} s  "
                  f"génération {result['output_generation_ms']/1000:6.2f} s  "
                  f"total {elapsed/1000:6.2f} s")
    print(f'Comparaison terminée : {output}', flush=True)


if __name__ == '__main__':
    main()
