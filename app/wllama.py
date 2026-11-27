"""Connect Clair's document pipeline to a browser running the local GGUF."""
from . import llamacpp, webnn

MODEL = 'qwen3-4b:wllama'
WEBGPU_MODEL = 'qwen3-4b:wllama-webgpu'
DEVICES = {MODEL: 'cpu', WEBGPU_MODEL: 'gpu'}
NAME = llamacpp.NAME
CONTEXT = llamacpp.CONTEXT
VERSION = '4.0.0'
PENDING = {}


async def generate(model, messages, reserve, schema):
    from .llm import ModelError

    device = DEVICES[model]
    result = await webnn.ACTIVE.get().request({
        'type': 'generate_wllama', 'messages': messages, 'schema': schema,
        'context': CONTEXT, 'max_tokens': reserve, 'device': device,
        'model_url': f'/api/wllama/model.gguf?v={llamacpp.MODEL_SHA256}',
    }, PENDING)
    if result['error']:
        raise ModelError(result['error'])
    if device == 'gpu' and (result['device'] != 'gpu' or not 0 < result['gpu_layers'] <= result['total_layers']):
        raise ModelError('Wllama n’a confirmé aucune couche sur le GPU. Essayez le mode Wllama CPU.')
    yield {'type': 'token', 'text': result['text']}
    metrics = {key: result[key] for key in (
        'done_reason', 'prompt_tokens', 'output_tokens', 'load_ms', 'prompt_evaluation_ms',
        'output_generation_ms', 'threads', 'generation_ms',
    )}
    if device == 'gpu':
        metrics.update(gpu_layers=result['gpu_layers'], total_layers=result['total_layers'])
    metrics.update(runtime='wllama', model=model, context=CONTEXT, device=device, model_calls=1)
    yield {'type': 'llm_metrics', 'metrics': metrics}
