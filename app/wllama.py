"""Connect Clair's document pipeline to a browser running the local GGUF."""
from . import llamacpp, webnn

MODEL = 'qwen3-4b:wllama'
NAME = llamacpp.NAME
CONTEXT = llamacpp.CONTEXT
VERSION = '4.0.0'
PENDING = {}


async def generate(messages, reserve, schema):
    from .llm import ModelError

    result = await webnn.ACTIVE.get().request({
        'type': 'generate_wllama', 'messages': messages, 'schema': schema,
        'context': CONTEXT, 'max_tokens': reserve,
        'model_url': f'/api/wllama/model.gguf?v={llamacpp.MODEL_SHA256}',
    }, PENDING)
    if result['error']:
        raise ModelError(result['error'])
    yield {'type': 'token', 'text': result['text']}
    metrics = {key: result[key] for key in (
        'done_reason', 'prompt_tokens', 'output_tokens', 'load_ms', 'prompt_evaluation_ms',
        'output_generation_ms', 'threads', 'generation_ms',
    )}
    metrics.update(runtime='wllama', model=MODEL, context=CONTEXT, device='cpu', model_calls=1)
    yield {'type': 'llm_metrics', 'metrics': metrics}
