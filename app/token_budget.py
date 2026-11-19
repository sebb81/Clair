"""Local Qwen 3.5 tokenizer, reconstructed from the installed GGUF via Ollama.

No model/tokenizer download. Other families retain the conservative byte bound.
Chat framing is reserved separately; native Ollama counts remain authoritative.
"""
from functools import lru_cache

PATTERN = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?[\p{L}\p{M}]+|\p{N}| ?[^\s\p{L}\p{M}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
COUNTERS = {}


def install(model, info):
    metadata = info.get('model_info', {})
    if metadata.get('tokenizer.ggml.pre') != 'qwen35':
        return
    from tokenizers import Tokenizer, Regex, models, pre_tokenizers
    vocab = metadata.get('tokenizer.ggml.tokens', [])
    merges = metadata.get('tokenizer.ggml.merges', [])
    if not vocab or not merges:
        return
    tokenizer = Tokenizer(models.BPE(vocab={v: i for i, v in enumerate(vocab)},
                                     merges=[tuple(m.split(' ', 1)) for m in merges]))
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(PATTERN), behavior='isolated'),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)])

    @lru_cache(maxsize=2048)
    def count(text):
        return len(tokenizer.encode(text, add_special_tokens=False).ids)
    COUNTERS[model] = count


def counter(model):
    return COUNTERS.get(model, lambda text: len(text.encode('utf-8')))


def method(model):
    if model not in COUNTERS:
        return 'utf8-byte-upper-bound'
    return 'webnn-local-bpe' if model.endswith(':webnn') else 'installed-qwen35-bpe'
