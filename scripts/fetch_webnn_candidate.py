"""Fetch pinned candidate files for the local WebNN benchmark."""
import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

REPO = 'webai-community/ai-models'
REVISION = 'e3a73840b0df9378a2d32650c751ab638a9b49a1'
CANDIDATES = ('Qwen2.5-3B-Instruct', 'Qwen3-4B', 'Qwen3.5-4B')


def download(url, output, info):
    size = info['size']
    if output.is_file() and output.stat().st_size == size:
        return
    target = output.with_suffix(output.suffix + '.partial')
    parts = []
    if size < 128 * 1024**2:
        subprocess.run(['curl.exe', '-fsSL', '--retry', '2', url, '-o', str(target)], check=True)
    else:
        block = 256 * 1024**2

        def fetch(start):
            end = min(start + block, size) - 1
            part = target.with_suffix(f'.range-{start}')
            expected = end - start + 1
            for _ in range(6):
                received = part.stat().st_size if part.is_file() else 0
                if received == expected:
                    break
                tail = part.with_suffix(part.suffix + '.tail')
                result = subprocess.run(['curl.exe', '-fsSL', '--max-time', '180',
                                         '--max-filesize', str(expected - received),
                                         '--range', f'{start + received}-{end}', url, '-o', str(tail)])
                if result.returncode in (0, 18, 28, 56) and tail.is_file():
                    if tail.stat().st_size > expected - received:
                        raise RuntimeError(f'Too many bytes for range {start}-{end}')
                    with part.open('ab') as dst, tail.open('rb') as src:
                        while data := src.read(4 * 1024**2):
                            dst.write(data)
                    tail.unlink()
            if part.stat().st_size != end - start + 1:
                raise RuntimeError(f'Downloaded range does not match {start}-{end}')
            print(f'{output.parent.name} {end + 1:,}/{size:,}', flush=True)
            return part

        with ThreadPoolExecutor(max_workers=6) as pool:
            parts = list(pool.map(fetch, range(0, size, block)))
        with target.open('wb') as stream:
            for part in parts:
                with part.open('rb') as source:
                    while data := source.read(4 * 1024**2):
                        stream.write(data)
    if target.stat().st_size != size:
        raise RuntimeError(f'Unexpected size for {output}')
    if lfs := info.get('lfs'):
        with target.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != lfs['sha256']:
                raise RuntimeError(f'SHA-256 mismatch for {output}')
    target.replace(output)
    for part in parts:
        part.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', choices=CANDIDATES)
    args = parser.parse_args()
    relative = args.model + '/onnx-webgpu/'
    root = Path('data/webnn-bench') / args.model.lower()
    root.mkdir(parents=True, exist_ok=True)
    with urlopen(f'https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true', timeout=20) as response:
        metadata = {item['rfilename']: item for item in json.load(response)['siblings']}
    entries = {}
    for name in ('model.onnx', 'tokenizer.json', 'tokenizer_config.json', 'genai_config.json', 'model.onnx.data'):
        info = metadata[relative + name]
        download(f'https://huggingface.co/{REPO}/resolve/{REVISION}/{relative}{name}', root / name, info)
        entries[name] = info
    (root / 'manifest.json').write_text(json.dumps(entries, indent=2), encoding='utf-8')
    print(f'{args.model} ready', flush=True)


if __name__ == '__main__':
    main()
