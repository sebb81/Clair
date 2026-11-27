import asyncio
import hashlib
import io
import json
import uuid
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from anyio import CancelScope
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import bergamot, engine, llamacpp, llm, translation, webnn, wllama
from .config import settings
from .extract import extract
from .store import db, document, initialize

compute_lock = asyncio.Lock()
import_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    initialize()
    yield


app = FastAPI(title='Clair — analyse documentaire locale', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None,
              telemetry={'tracing': False, 'metrics': False, 'logs': False, 'auto_configure': False})
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])


class BodyLimitMiddleware:
    """Bound incoming body even without Content-Length, before multipart spooling."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        received = 0
        async def limited_receive():
            nonlocal received
            event = await receive()
            received += len(event.get('body', b''))
            if received > (settings.max_upload_mb + 1) * 1024 * 1024:
                raise HTTPException(413, 'Taille maximale de requête dépassée.')
            return event
        await self.app(scope, limited_receive, send)


app.add_middleware(BodyLimitMiddleware)


@app.middleware('http')
async def local_only(request: Request, call_next):
    origin = request.headers.get('origin')
    if origin:
        parsed = urlparse(origin)
        if parsed.scheme != 'http' or parsed.hostname not in ['127.0.0.1', 'localhost', 'testserver'] or parsed.port not in [None, 5173, 8765]:
            return JSONResponse({'detail': 'Origine distante refusée.'}, 403)
    if request.headers.get('sec-fetch-site') == 'cross-site':
        return JSONResponse({'detail': 'Requête intersite refusée.'}, 403)
    size = request.headers.get('content-length')
    if size and int(size) > (settings.max_upload_mb + 1) * 1024 * 1024:
        return JSONResponse({'detail': 'Fichier trop volumineux.'}, 413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    # ONNX Runtime's Emscripten glue compiles JS bindings inside the worker.
    path = request.url.path
    worker = path.startswith('/assets/webnn-worker-') and path.endswith('.js')
    wasm_worker = path.startswith('/assets/wllama-worker-') and path.endswith('.js')
    script = "script-src 'self' 'unsafe-eval'" if worker else "script-src 'self'"
    children = "worker-src 'self'"
    if wasm_worker:
        script = "script-src 'self' 'wasm-unsafe-eval' blob:"
        children += ' blob:'
    response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
    response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
    response.headers['Content-Security-Policy'] = (
        f"default-src 'self'; {script}; {children}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
    return response


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({'detail': str(exc)}, 404)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, 400)


@app.get('/api/health')
def health():
    models = [spec.health(model) for model, spec in webnn.MODELS.items() if spec.installed()]
    recommended = models[-1] if models else None
    native = {'model': llamacpp.MODEL, 'name': llamacpp.NAME,
              'context': llamacpp.CONTEXT, 'installed': llamacpp.installed()}
    wasm = {'model': wllama.MODEL, 'name': wllama.NAME, 'context': wllama.CONTEXT,
            'installed': llamacpp.weights_installed()}
    return {'mode': 'webnn', 'webnn': recommended, 'webnn_models': models,
            'llamacpp_model': native, 'wllama_model': wasm,
            'wllama_webgpu_model': {**wasm, 'model': wllama.WEBGPU_MODEL},
            'recommended_model': recommended['model'] if recommended else None,
            'busy': compute_lock.locked() or import_lock.locked(), 'max_upload_mb': settings.max_upload_mb}


@app.get('/api/webnn/assets/{name}')
def webnn_asset(name: str):
    return webnn_model_asset(webnn.MODELS[webnn.MODEL].folder, name)


@app.api_route('/api/wllama/model.gguf', methods=['GET', 'HEAD'])
def wllama_model():
    if not llamacpp.weights_installed():
        raise HTTPException(404, 'Le fichier Qwen3 4B GGUF est absent.')
    return FileResponse(llamacpp.directory() / llamacpp.MODEL_FILE, media_type='application/octet-stream')


@app.get('/api/webnn/models/{folder}/assets/{name}')
def webnn_model_asset(folder: str, name: str):
    spec = next((item for item in webnn.MODELS.values() if item.folder == folder), None)
    if spec is None or name not in spec.assets or not spec.installed():
        raise HTTPException(404, 'Modèle WebNN absent. Lancez installer.bat.')
    return FileResponse(spec.asset(name), headers={'Cache-Control': 'no-cache'})


class BrowserResult(BaseModel):
    error: str | None = Field(default=None, max_length=2000)
    text: str = Field(default='', max_length=32000)
    prompt_tokens: int = Field(default=0, ge=0, le=webnn.MAX_CONTEXT)
    output_tokens: int = Field(default=0, ge=0, le=webnn.MAX_CONTEXT)
    context_tokens: int = Field(default=0, ge=0, le=webnn.MAX_CONTEXT)
    prefill_tokens: int = Field(default=0, ge=0, le=webnn.MAX_CONTEXT)
    done_reason: str = Field(default='stop', pattern='^(stop|length)$')
    dispatches: int = Field(default=0, ge=0)
    device: str = Field(default='cpu', pattern='^(gpu|cpu|npu)$')
    device_preference: str = Field(default='auto', pattern='^(auto|gpu|cpu|npu)$')
    device_attempts: list[dict] = Field(default_factory=list, max_length=3)
    device_verification: str = Field(default='webnn-context-and-generation', max_length=80)
    hardware_identity_verified: bool = False
    accelerator_check_ms: float = Field(default=0, ge=0)
    gpu_check_ms: float = Field(default=0, ge=0)
    gpu_fallback_ms: float = Field(default=0, ge=0)
    load_ms: float = Field(default=0, ge=0)
    prompt_evaluation_ms: float = Field(default=0, ge=0)
    output_generation_ms: float = Field(default=0, ge=0)


class WllamaResult(BrowserResult):
    threads: int = Field(default=1, ge=1, le=8)
    generation_ms: float = Field(default=0, ge=0)
    gpu_layers: int = Field(default=0, ge=0)
    total_layers: int = Field(default=0, ge=0)


@app.post('/api/wllama/results/{request_id}')
async def wllama_result(request_id: str, body: WllamaResult):
    pending = wllama.PENDING.get(request_id)
    if pending is None or pending.done():
        raise HTTPException(410, 'Calcul Wllama déjà terminé ou interrompu.')
    pending.set_result(body.model_dump())
    return {'accepted': True}


@app.post('/api/webnn/results/{request_id}')
async def webnn_result(request_id: str, body: BrowserResult):
    pending = webnn.PENDING.get(request_id)
    if pending is None or pending.done():
        raise HTTPException(410, 'Calcul WebNN déjà terminé ou interrompu.')
    if not body.error and body.dispatches < 1:
        raise HTTPException(400, 'Aucune exécution WebNN reçue.')
    pending.set_result(body.model_dump())
    return {'accepted': True}


@app.get('/api/documents')
def documents():
    with db() as c:
        return [dict(r) for r in c.execute('SELECT id,name,kind,pages,status,created FROM documents ORDER BY created DESC')]


@app.get('/api/documents/{doc}')
def get_document(doc: str):
    return document(doc)


@app.post('/api/documents')
async def upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in ['.pdf', '.docx', '.txt']:
        raise HTTPException(400, 'Formats acceptés : PDF, DOCX, TXT UTF-8.')
    name = (file.filename or 'document').replace('\\', '/').split('/')[-1][:200]
    temp = settings.data_dir / 'files' / (uuid.uuid4().hex + suffix)
    digest, total = hashlib.sha256(), 0
    try:
        with temp.open('wb') as out:
            while part := await file.read(1024 * 1024):
                total += len(part)
                if total > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, 'Taille maximale dépassée.')
                digest.update(part)
                out.write(part)
        if total == 0:
            raise HTTPException(400, 'Fichier vide.')
        with temp.open('rb') as check:
            signature = check.read(8)
        if suffix == '.pdf' and not signature.startswith(b'%PDF-'):
            raise HTTPException(400, 'Le fichier ne contient pas une signature PDF valide.')
        if suffix == '.docx' and not signature.startswith(b'PK'):
            raise HTTPException(400, 'Le fichier ne contient pas une archive DOCX valide.')
        final = settings.data_dir / 'files' / (digest.hexdigest() + suffix)
        async with import_lock:
            if final.exists():
                temp.unlink()
            else:
                temp.replace(final)
            try:
                result, cached = await asyncio.to_thread(extract, final, name, digest.hexdigest())
            except Exception as exc:
                # Invalid file content must be a user-facing error, never an HTTP 500.
                try:
                    final.unlink(missing_ok=True)
                except OSError:
                    # A native parser may retain its handle during exception unwinding on Windows.
                    # Retry cleanup on a subsequent import; never obscure the extraction error.
                    pass
                raise HTTPException(400, f'Extraction impossible : {exc}') from exc
        return {'document': result, 'cached': cached}
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


DEMO = '''# Chapitre 1 — Projet Horizon
Le projet Horizon modernise les archives de la ville. La décision du comité est de lancer un pilote en mars 2027. La responsable est Nadia Martin.

# Chapitre 2 — Budget
Le budget annoncé pour 2027 est de 240 000 euros. Il se répartit en équipement (90 000 euros), formation (50 000 euros) et numérisation (100 000 euros).

# Chapitre 3 — Risques et calendrier
Deux risques sont identifiés : le retard de livraison des scanners et la disponibilité des archivistes. Le pilote commence en mars 2027 ; le déploiement est prévu en septembre 2027. Aucun budget pour 2028 n'est indiqué.

# Chapitre 4 — Décisions
Le comité demande une revue mensuelle des coûts et une sauvegarde locale quotidienne. Le prestataire reste à sélectionner. La date de sélection n'est pas fixée.
'''


@app.post('/api/demo')
async def demo():
    raw = DEMO.encode('utf-8')
    digest = hashlib.sha256(raw).hexdigest()
    path = settings.data_dir / 'files' / (digest + '.txt')
    async with import_lock:
        path.write_bytes(raw)
        result, cached = await asyncio.to_thread(extract, path, 'Démonstration — Projet Horizon.txt', digest)
    return {'document': result, 'cached': cached}


@app.get('/api/documents/{doc}/pages/{number}')
def page(doc: str, number: int):
    info = document(doc)
    with db() as c:
        row = c.execute('SELECT * FROM pages WHERE doc=? AND number=?', (doc, number)).fetchone()
    if not row:
        raise HTTPException(404, 'Page ou bloc introuvable.')
    return {**dict(row), 'tables': json.loads(row['tables']), 'physical_page': info['kind'] == 'pdf'}


@app.get('/api/documents/{doc}/sources/{source_id}')
def source(doc: str, source_id: int):
    with db() as c:
        row = c.execute('SELECT * FROM chunks WHERE doc=? AND id=?', (doc, source_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Source introuvable.')
        return dict(row)


@app.get('/api/documents/{doc}/original')
def original(doc: str):
    document(doc)
    with db() as c:
        row = c.execute('SELECT path,name,kind FROM documents WHERE id=?', (doc,)).fetchone()
    return FileResponse(row['path'], media_type='application/pdf' if row['kind'] == 'pdf' else 'application/octet-stream',
                        filename=row['name'], content_disposition_type='inline' if row['kind'] == 'pdf' else 'attachment')


@app.get('/api/documents/{doc}/messages')
def history(doc: str):
    document(doc)
    with db() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM messages WHERE doc=? ORDER BY id DESC LIMIT 100', (doc,))]
    return [{**r, 'sources': json.loads(r['sources']), 'metrics': json.loads(r['metrics'])} for r in reversed(rows)]


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    model: str = Field(min_length=1, max_length=120)
    strategy: str = Field(default='auto', pattern='^(auto|fast|direct|summary|hybrid|bm25|section)$')
    output_format: str = Field(default='réponse détaillée', pattern='^(réponse courte|réponse détaillée|résumé structuré|points clés)$')
    prepare_only: bool = False
    webnn_device: str = Field(default='auto', pattern='^(auto|cpu|gpu|npu)$')


@app.post('/api/documents/{doc}/ask')
async def ask(doc: str, body: Question):
    document(doc)

    async def operation(events):
        if body.prepare_only:
            with llm.trace(doc):
                digest = await llm.validate_model(body.model)
                progress = {}
                preparation = asyncio.create_task(engine.prepare(doc, body.model, digest, progress=progress))
                try:
                    while not preparation.done():
                        await asyncio.wait({preparation}, timeout=1)
                        if progress and not preparation.done():
                            await events.put({'type': 'status', 'text':
                                f"{progress.get('stage', 'Préparation')} · "
                                f"{progress.get('stage_completed', 0)}/{progress.get('stage_total', '?')} lots"})
                    preparation.result()
                finally:
                    preparation.cancel()
                    await asyncio.gather(preparation, return_exceptions=True)
            await events.put({'type': 'prepared'})
        else:
            async with aclosing(engine.answer(doc, body.question, body.model, body.strategy, body.output_format)) as response:
                async for event in response:
                    await events.put(event)

    if body.model == llamacpp.MODEL:
        if not llamacpp.installed():
            raise HTTPException(400, 'Installez le modèle CPU avec python -m scripts.benchmark_cpu --install-only.')
        events = asyncio.Queue()

        async def run():
            async with llamacpp.session():
                await operation(events)

        return await compute_response(events, run)
    if body.model in wllama.DEVICES:
        if not llamacpp.weights_installed():
            raise HTTPException(400, 'Installez le GGUF avec python -m scripts.benchmark_cpu --install-gguf.')
        return await browser_job(webnn.Browser(wllama.DEVICES[body.model], body.model, wllama.CONTEXT),
                                 lambda browser: operation(browser.events))
    return await browser_response(body.model, body.webnn_device, lambda browser: operation(browser.events))


async def browser_response(model, device, operation):
    if model not in webnn.MODELS:
        raise HTTPException(400, 'Choisissez un modèle WebNN dans Clair.')
    if not webnn.MODELS[model].installed():
        raise HTTPException(400, 'Le modèle WebNN choisi doit être installé.')
    return await browser_job(webnn.Browser(device, model), operation)


async def browser_job(browser, operation):
    async def run():
        context = webnn.ACTIVE.set(browser)
        try:
            await operation(browser)
        finally:
            webnn.ACTIVE.reset(context)

    return await compute_response(browser.events, run)


async def compute_response(events, operation):
    if compute_lock.locked():
        raise HTTPException(409, 'Un calcul est en cours. Arrêtez-le ou attendez sa fin.')
    await compute_lock.acquire()

    async def stream():
        async def run():
            try:
                await operation()
            except Exception as exc:
                await events.put({'type': 'error', 'message': str(exc)})
            finally:
                events.put_nowait(None)

        task = asyncio.create_task(run())
        try:
            while (event := await events.get()) is not None:
                yield json.dumps(event, ensure_ascii=False) + '\n'
        finally:
            try:
                task.cancel()
                # Starlette cancels the streaming scope on disconnect. Finish
                # cancelling the job before opening the lock again.
                with CancelScope(shield=True):
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                compute_lock.release()

    return StreamingResponse(stream(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-store'})


class TranslationRequest(BaseModel):
    language: str = Field(pattern='^(en|fr|es|de|it|pt|nl)$')
    model: str | None = Field(default=None, min_length=1, max_length=120)
    engine: str = Field(default='webnn', pattern='^(webnn|bergamot)$')
    source_language: str | None = Field(default=None, pattern='^(fr|en)$')
    webnn_device: str = Field(default='auto', pattern='^(auto|cpu|gpu|npu)$')


@app.get('/api/documents/{doc}/translations')
def translations(doc: str):
    return {'languages': {key: names[0] for key, names in translation.LANGUAGES.items()},
            'bergamot_pairs': [{'source': model.source, 'target': model.target, 'installed': model.installed()}
                               for model in bergamot.MODELS.values()],
            'translations': translation.history(doc)}


@app.post('/api/documents/{doc}/translate')
async def translate(doc: str, body: TranslationRequest):
    document(doc)

    async def operation(queue, model):
        async with aclosing(translation.translate(doc, body.language, model)) as events:
            async for event in events:
                await queue.put(event)

    if body.engine == 'bergamot':
        native = next((model for model in bergamot.MODELS.values()
                       if (model.source, model.target) == (body.source_language, body.language)), None)
        if not native:
            raise HTTPException(400, 'Choisissez une direction français ↔ anglais pour Bergamot.')
        if not native.installed():
            raise HTTPException(400, 'Installez Bergamot avec installer-traduction.bat.')
        queue = asyncio.Queue()
        return await compute_response(queue, lambda: operation(queue, native.id))

    if not body.model:
        raise HTTPException(422, 'Choisissez un modèle WebNN dans Clair.')
    return await browser_response(body.model, body.webnn_device,
                                  lambda browser: operation(browser.events, body.model))


@app.get('/api/documents/{doc}/translations/{translation_id}/download')
def translation_download(doc: str, translation_id: str):
    content = translation.export_docx(doc, translation_id)
    job = translation.get(doc, translation_id)
    name = Path(document(doc)['name']).stem + f"-{job['language']}.docx"
    return StreamingResponse(io.BytesIO(content),
                             media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                             headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(name),
                                      'Cache-Control': 'no-store'})


@app.delete('/api/documents/{doc}')
async def delete(doc: str):
    if compute_lock.locked() or import_lock.locked():
        raise HTTPException(409, 'Attendez la fin du traitement avant de supprimer un document.')
    document(doc)
    with db() as c:
        row = c.execute('SELECT path FROM documents WHERE id=?', (doc,)).fetchone()
        c.execute('DELETE FROM search WHERE doc=?', (doc,))
        c.execute('DELETE FROM documents WHERE id=?', (doc,))
    Path(row['path']).unlink(missing_ok=True)
    return {'deleted': True}


DIST = Path(__file__).resolve().parent.parent / 'web' / 'dist'
if DIST.exists():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='frontend')
