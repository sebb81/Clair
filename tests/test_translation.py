import asyncio
import io
import json
import re
from contextlib import aclosing, asynccontextmanager

import pytest
from docx import Document
from fastapi.testclient import TestClient

from app import bergamot, token_budget, translation, webnn
from app.extract import extract
from app.main import app, browser_response, compute_lock, compute_response
from app.store import db, initialize


@pytest.fixture
def translator(monkeypatch):
    def validate(model):
        token_budget.COUNTERS[model] = lambda text: (len(text) + 3) // 4
        return webnn.MODELS[model].digest
    monkeypatch.setattr(webnn, 'validate', validate)
    monkeypatch.setattr(webnn.LocalModel, 'installed', lambda self: True)
    yield
    token_budget.COUNTERS.clear()


def run_translation(doc, model=webnn.QWEN3, language='en', generate=None):
    async def run():
        browser = webnn.Browser('cpu', model)
        if generate:
            browser.generate = generate
        token = webnn.ACTIVE.set(browser)
        try:
            async with aclosing(translation.translate(doc, language, model)) as events:
                return [event async for event in events]
        finally:
            webnn.ACTIVE.reset(token)
    return asyncio.run(run())


async def echo(messages, *args):
    return {'text': messages[1]['content'].split('SOURCE\n', 1)[1].rsplit('\nEND SOURCE', 1)[0],
            'done_reason': 'stop', 'output_tokens': 10, 'dispatches': 1}


def test_all_source_text_and_headings_are_planned_in_order(imported, translator):
    job = run_translation(imported['id'], generate=echo)[-1]['translation']
    assert job['status'] == 'complete'
    with db() as c:
        pages = list(c.execute('SELECT number,text FROM pages WHERE doc=? ORDER BY number', (imported['id'],)))
        blocks = list(c.execute('SELECT * FROM translation_blocks WHERE translation=? ORDER BY position', (job['id'],)))
        assert [b['page'] for b in blocks] == sorted(b['page'] for b in blocks)
        for page in pages:
            reconstructed = ''.join(b['source'] for b in blocks if b['page'] == page['number'])
            assert re.sub(r'\s', '', reconstructed) == re.sub(r'\s', '', page['text'])
        assert any(b['heading'] for b in blocks)
        assert c.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM summaries').fetchone()[0] == 0


def test_interruption_retains_completed_blocks_and_resume_skips_them(imported, translator):
    calls = []
    async def interrupted(messages, *args):
        calls.append(messages)
        if len(calls) == 2:
            raise asyncio.CancelledError()
        return await echo(messages)
    with pytest.raises(asyncio.CancelledError):
        run_translation(imported['id'], generate=interrupted)
    job = translation.history(imported['id'])[0]
    assert job['completed'] == 1 and job['status'] == 'paused'
    translated = []
    async def resume(messages, *args):
        translated.append(messages)
        return await echo(messages)
    final = run_translation(imported['id'], generate=resume)[-1]['translation']
    assert final['id'] == job['id']
    assert len(translated) == final['total'] - 1
    assert calls[0] not in translated
    assert final['completed'] == final['total']
    # Completed translations require no model invocation.
    assert len(run_translation(imported['id'], generate=resume)) == 1
    assert len(translated) == final['total'] - 1


def test_truncated_output_is_split_without_dropping_source(imported, translator):
    attempts = []
    async def truncated(messages, *args):
        source = messages[1]['content'].split('SOURCE\n', 1)[1].rsplit('\nEND SOURCE', 1)[0]
        attempts.append(source)
        if len(source) > 90:
            return {'text': 'INCOMPLETE', 'done_reason': 'length'}
        return await echo(messages)
    job = run_translation(imported['id'], generate=truncated)[-1]['translation']
    assert job['status'] == 'complete'
    with db() as c:
        rows = list(c.execute('SELECT * FROM translation_blocks WHERE translation=? ORDER BY position', (job['id'],)))
        assert all('INCOMPLETE' != r['text'] for r in rows)
        assert any('.' in r['position'] for r in rows)
        for page in c.execute('SELECT * FROM pages WHERE doc=?', (imported['id'],)):
            assert re.sub(r'\s', '', ''.join(r['source'] for r in rows if r['page'] == page['number'])) == re.sub(r'\s', '', page['text'])


def test_failure_never_creates_complete_translation_or_download(imported, translator):
    async def empty(*args):
        return {'text': '', 'done_reason': 'stop'}
    with pytest.raises(ValueError, match='ne termine pas'):
        run_translation(imported['id'], generate=empty)
    job = translation.history(imported['id'])[0]
    assert job['status'] == 'error' and job['completed'] == 0
    with pytest.raises(ValueError, match='Terminez'):
        translation.export_docx(imported['id'], job['id'])


def test_cache_separates_languages_models_and_versions(imported, translator, monkeypatch):
    first = run_translation(imported['id'], generate=echo)[-1]['translation']
    french = run_translation(imported['id'], language='fr', generate=echo)[-1]['translation']
    other_model = run_translation(imported['id'], model=webnn.QWEN25, generate=echo)[-1]['translation']
    monkeypatch.setattr(translation, 'VERSION', 'new-version')
    updated = run_translation(imported['id'], generate=echo)[-1]['translation']
    assert len({j['id'] for j in (first, french, other_model, updated)}) == 4


def test_export_contains_ordered_translated_text_and_source_markers(imported, translator):
    index = 0
    async def translated(messages, *args):
        nonlocal index
        index += 1
        return {'text': f'Translated passage {index}.\nPreserve 240 000 euros.', 'done_reason': 'stop'}
    job = run_translation(imported['id'], generate=translated)[-1]['translation']
    content = translation.export_docx(imported['id'], job['id'])
    doc = Document(io.BytesIO(content))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert [p.text for p in doc.paragraphs if p.style.name == 'Heading 1'] == [f'Page source {i}' for i in range(1, 5)]
    assert text.index('Translated passage 1.') < text.index(f'Translated passage {index}.')
    assert '240 000 euros' in text
    assert doc.paragraphs[0].style.name == 'Title'


def test_no_text_refuses_translation_and_scan_warning_is_retained(imported, translator):
    with db() as c:
        c.execute("UPDATE documents SET warnings=? WHERE id=?", (json.dumps(['Page 2 scannée : OCR requis.']), imported['id']))
    job = run_translation(imported['id'], generate=echo)[-1]['translation']
    assert 'Page 2 scannée : OCR requis.' in job['warnings']
    with db() as c:
        c.execute('DELETE FROM translations')
        c.execute("UPDATE pages SET text='' WHERE doc=?", (imported['id'],))
    with pytest.raises(ValueError, match='Aucun texte'):
        run_translation(imported['id'], generate=echo)
    assert translation.history(imported['id']) == []


def test_wordless_unicode_split_preserves_every_character():
    text = '你好世界' * 300 + '\n' + 'abc' * 300
    parts = list(translation.split_source(text, lambda s: len(s.encode('utf-8'))))
    assert ''.join(parts) == text
    assert all(len(p.encode('utf-8')) <= 240 for p in parts)


@pytest.mark.parametrize('device', ['auto', 'cpu', 'gpu', 'npu'])
def test_api_translation_download_lock_validation_and_delete(imported, translator, monkeypatch, device):
    async def generate(self, messages, *args):
        assert self.device == device
        assert 'into English' in messages[0]['content']
        return await echo(messages)
    monkeypatch.setattr(webnn.Browser, 'generate', generate)
    doc = imported['id']
    with TestClient(app) as client:
        url = f'/api/documents/{doc}'
        assert client.get(url+'/translations').json()['languages']['en'] == 'Anglais'
        assert client.post(url+'/translate', json={'model': webnn.QWEN3, 'language': 'xx'}).status_code == 422
        assert client.post(url+'/translate', json={'model': 'cloud', 'language': 'en'}).status_code == 400
        asyncio.run(compute_lock.acquire())
        try:
            assert client.post(url+'/translate', json={'model': webnn.QWEN3, 'language': 'en'}).status_code == 409
        finally:
            compute_lock.release()
        response = client.post(url+'/translate', json={'model': webnn.QWEN3, 'language': 'en', 'webnn_device': device})
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1]['type'] == 'translation_done'
        job = events[-1]['translation']
        download = client.get(url+f"/translations/{job['id']}/download")
        assert download.status_code == 200
        assert 'attachment' in download.headers['content-disposition']
        assert Document(io.BytesIO(download.content)).paragraphs
        assert client.get(f"/api/documents/other/translations/{job['id']}/download").status_code == 404
        assert not compute_lock.locked()
        assert client.delete(url).status_code == 200
    with db() as c:
        assert c.execute('SELECT count(*) FROM translations').fetchone()[0] == 0
        assert c.execute('SELECT count(*) FROM translation_blocks').fetchone()[0] == 0


def test_restart_retains_partial_jobs(imported, translator):
    token_budget.COUNTERS[webnn.QWEN3] = len
    job = translation.create(imported['id'], 'en', webnn.QWEN3)
    with db() as c:
        c.execute("UPDATE translations SET status='running' WHERE id=?", (job['id'],))
    initialize()
    assert translation.get(imported['id'], job['id'])['status'] == 'paused'


def test_bergamot_disconnect_closes_session_and_preserves_native_blocks(imported, monkeypatch):
    model = bergamot.MODELS['fr-en-tiny:bergamot']
    completed_sources = []
    interrupted = True
    closed = []

    class FakeBergamot:
        async def translate(self, source, model_id):
            assert model_id == 'local-fr-en'
            if interrupted and completed_sources:
                await asyncio.Event().wait()
            completed_sources.append(source)
            return {'text': 'Translated passage.', 'done_reason': 'stop', 'device': 'cpu'}

    @asynccontextmanager
    async def session(selected):
        assert selected == model
        try:
            yield FakeBergamot(), 'local-fr-en'
        finally:
            closed.append(True)

    monkeypatch.setattr(bergamot.Model, 'installed', lambda self: True)
    monkeypatch.setattr(bergamot, 'open_session', session)

    async def run():
        nonlocal interrupted
        doc = imported['id']
        queue = asyncio.Queue()

        async def operation():
            async with aclosing(translation.translate(doc, 'en', model.id)) as events:
                async for event in events:
                    await queue.put(event)

        response = await compute_response(queue, operation)
        async with aclosing(response.body_iterator) as stream:
            async for item in stream:
                event = json.loads(item)
                if event['type'] == 'translation_progress' and event['translation']['completed'] == 1:
                    break
        assert closed == [True]
        assert not compute_lock.locked()
        partial = translation.history(doc)[0]
        assert partial['status'] == 'paused' and partial['completed'] == 1
        assert partial['engine'] == 'bergamot' and partial['source_language'] == 'fr'

        interrupted = False
        async with aclosing(translation.translate(doc, 'en', model.id)) as events:
            final = [item async for item in events][-1]['translation']
        assert final['id'] == partial['id'] and final['status'] == 'complete'
        assert final['devices'] == [{'device': 'cpu', 'blocks': final['total']}]
        assert len(completed_sources) == final['total']
        assert completed_sources[0] not in completed_sources[1:]
        assert closed == [True, True]

    asyncio.run(run())


def test_disconnect_cancels_pending_browser_request_and_releases_lock(imported, translator):
    async def run():
        async def operation(browser):
            async with aclosing(translation.translate(imported['id'], 'en', webnn.QWEN3)) as events:
                async for event in events:
                    await browser.events.put(event)
        response = await browser_response(webnn.QWEN3, 'cpu', operation)
        async with aclosing(response.body_iterator) as stream:
            while True:
                event = json.loads(await anext(stream))
                if event['type'] == 'generate':
                    assert event['context'] == 1024
                    assert event['max_tokens'] == 512
                    request_id = event['id']
                    assert request_id in webnn.PENDING
                    break
        assert request_id not in webnn.PENDING
        assert not compute_lock.locked()
        assert translation.history(imported['id'])[0]['status'] == 'paused'
    asyncio.run(run())


def test_translation_splits_oversized_prompts_before_browser_call(imported, translator, monkeypatch):
    # Simulate unexpectedly expensive framing for a long block. It must be split
    # without repeatedly compiling another, larger context or losing the source.
    original = translation.messages
    monkeypatch.setattr(translation, 'messages', lambda text, lang:
                        original(text, lang) if len(text) < 100 else
                        [{'role': 'system', 'content': 'x' * 2048}, original(text, lang)[1]])
    seen = []
    async def generate(messages, context, reserve, json_output, profile):
        assert context == 1024 and reserve == 512
        assert len(messages[0]['content']) < 500
        seen.append(messages)
        return await echo(messages)
    job = run_translation(imported['id'], generate=generate)[-1]['translation']
    assert job['completed'] == job['total'] == len(seen)
    with db() as c:
        rows = list(c.execute('SELECT source,page FROM translation_blocks WHERE translation=? ORDER BY position', (job['id'],)))
        for page in c.execute('SELECT number,text FROM pages WHERE doc=?', (imported['id'],)):
            assert re.sub(r'\s', '', ''.join(r['source'] for r in rows if r['page'] == page['number'])) == re.sub(r'\s', '', page['text'])


@pytest.mark.parametrize('preference', ['auto', 'cpu', 'gpu', 'npu'])
@pytest.mark.parametrize('prepare', [False, True])
def test_questions_and_summary_preparation_share_device_preference(imported, translator, monkeypatch, preference, prepare):
    from app import engine
    async def answer(*args):
        assert webnn.ACTIVE.get().device == preference
        yield {'type': 'done', 'answer': 'Fait.', 'sources': [], 'metrics': {}}
    async def prepare_summary(*args, **kwargs):
        assert webnn.ACTIVE.get().device == preference
    monkeypatch.setattr(engine, 'answer', answer)
    monkeypatch.setattr(engine, 'prepare', prepare_summary)
    with TestClient(app) as client:
        response = client.post(f"/api/documents/{imported['id']}/ask", json={
            'question': 'Résume le document.', 'model': webnn.QWEN3,
            'webnn_device': preference, 'prepare_only': prepare})
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]['type'] == ('prepared' if prepare else 'done')
    assert not compute_lock.locked()


def test_resuming_translation_can_mix_preserved_cpu_and_new_npu_blocks(imported, translator):
    calls = 0
    async def cpu_then_pause(messages, *args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError()
        return {**await echo(messages), 'device': 'cpu'}
    with pytest.raises(asyncio.CancelledError):
        run_translation(imported['id'], generate=cpu_then_pause)
    async def npu(messages, *args):
        return {**await echo(messages), 'device': 'npu'}
    job = run_translation(imported['id'], generate=npu)[-1]['translation']
    assert job['devices'] == [{'device': 'cpu', 'blocks': 1}, {'device': 'npu', 'blocks': job['total'] - 1}]
