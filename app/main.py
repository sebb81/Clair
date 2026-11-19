import asyncio
import hashlib
import json
import uuid
from contextlib import aclosing, asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from anyio import CancelScope
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import engine, llm, webnn
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
    worker = request.url.path.startswith('/assets/webnn-worker-') and request.url.path.endswith('.js')
    script = "script-src 'self' 'unsafe-eval'" if worker else "script-src 'self'"
    response.headers['Content-Security-Policy'] = (
        f"default-src 'self'; {script}; worker-src 'self'; style-src 'self' 'unsafe-inline'; "
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
    return {'mode': 'webnn', 'webnn': recommended, 'webnn_models': models,
            'recommended_model': recommended['model'] if recommended else None,
            'busy': compute_lock.locked(), 'max_upload_mb': settings.max_upload_mb}


@app.get('/api/webnn/assets/{name}')
def webnn_asset(name: str):
    return webnn_model_asset(webnn.MODELS[webnn.MODEL].folder, name)


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
    done_reason: str = Field(default='stop', pattern='^(stop|length)$')
    dispatches: int = Field(default=0, ge=0)
    device: str = Field(default='gpu', pattern='^(gpu|cpu)$')
    gpu_check_ms: float = Field(default=0, ge=0)
    gpu_fallback_ms: float = Field(default=0, ge=0)
    load_ms: float = Field(default=0, ge=0)
    prompt_evaluation_ms: float = Field(default=0, ge=0)
    output_generation_ms: float = Field(default=0, ge=0)


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
    webnn_device: str = Field(default='auto', pattern='^(auto|cpu)$')


@app.post('/api/documents/{doc}/ask')
async def ask(doc: str, body: Question):
    document(doc)
    if body.model not in webnn.MODELS:
        raise HTTPException(400, 'Choisissez un modèle WebNN dans Clair.')
    if not webnn.MODELS[body.model].installed():
        raise HTTPException(400, 'Le modèle WebNN choisi doit être installé.')
    if compute_lock.locked():
        raise HTTPException(409, 'Un calcul est en cours. Arrêtez-le ou attendez sa fin.')
    await compute_lock.acquire()

    async def browser_stream():
        browser = webnn.Browser(body.webnn_device, body.model)

        async def run():
            context = webnn.ACTIVE.set(browser)
            try:
                if body.prepare_only:
                    with llm.trace(doc):
                        digest = await llm.validate_model(body.model)
                        progress = {}
                        preparation = asyncio.create_task(engine.prepare(doc, body.model, digest, progress=progress))
                        try:
                            while not preparation.done():
                                await asyncio.wait({preparation}, timeout=1)
                                if progress and not preparation.done():
                                    await browser.events.put({'type': 'status', 'text':
                                        f"{progress.get('stage', 'Préparation')} · "
                                        f"{progress.get('stage_completed', 0)}/{progress.get('stage_total', '?')} lots"})
                            preparation.result()
                        finally:
                            preparation.cancel()
                            await asyncio.gather(preparation, return_exceptions=True)
                    await browser.events.put({'type': 'prepared'})
                else:
                    async with aclosing(engine.answer(doc, body.question, body.model, body.strategy, body.output_format)) as response:
                        async for event in response:
                            await browser.events.put(event)
            except Exception as exc:
                await browser.events.put({'type': 'error', 'message': str(exc)})
            finally:
                webnn.ACTIVE.reset(context)
                browser.events.put_nowait(None)

        task = asyncio.create_task(run())
        try:
            while (event := await browser.events.get()) is not None:
                yield json.dumps(event, ensure_ascii=False) + '\n'
        finally:
            try:
                task.cancel()
                # Starlette cancels the streaming scope on disconnect. Finish
                # cancelling the browser request before opening the lock again.
                with CancelScope(shield=True):
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                compute_lock.release()

    return StreamingResponse(browser_stream(), media_type='application/x-ndjson',
                             headers={'Cache-Control': 'no-store'})


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
