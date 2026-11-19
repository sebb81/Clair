"""Adapt a fixed-cache Qwen GenAI graph for Clair's padded WebNN prefill.

Requires onnx. Keeps weights bit-for-bit and keeps individual external files
below the browser's 2 GiB boundary.
"""
import argparse
import json
from pathlib import Path

import onnx
from onnx import TensorProto, helper
from onnx.external_data_helper import uses_external_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', choices=('qwen2.5-3b-instruct', 'qwen3-4b', 'phi4-mini'))
    args = parser.parse_args()
    source = Path('data/webnn-bench') / args.model
    output = source / 'webnn'
    output.mkdir(exist_ok=True)
    model = onnx.load(source / 'model.onnx', load_external_data=False)
    graph = model.graph
    config = json.loads((source / 'genai_config.json').read_text(encoding='utf-8'))['model']
    decoder = config['decoder']
    head = next((n for n in graph.node if n.name == '/lm_head/prune/Gather'), None)
    if head is not None:
        head.input[1] = 'clair_logits_index'
    else:
        index = next(i for i, n in enumerate(graph.node) if 'logits' in n.output)
        logits = graph.node[index]
        feature = logits.input[0]
        logits.input[0] = 'clair_selected_hidden'
        graph.initializer.append(helper.make_tensor('clair_sequence_axis', TensorProto.INT64, [1], [1]))
        graph.node.insert(index, helper.make_node('Gather', [feature, 'clair_logits_index'], ['clair_last_hidden'], axis=1))
        graph.node.insert(index + 1, helper.make_node('Unsqueeze',
                          ['clair_last_hidden', 'clair_sequence_axis'], ['clair_selected_hidden']))
        graph.output[0].type.tensor_type.shape.dim[1].dim_value = 1
    graph.input.append(helper.make_tensor_value_info('clair_logits_index', TensorProto.INT64, []))

    # ORT's WebNN GQA needs a compile-time total length. The mask still
    # supplies the real number of valid tokens in the padded cache.
    if args.model != 'phi4-mini':
        for n in graph.node:
            if n.op_type == 'GroupQueryAttention':
                n.input[6] = 'clair_cache_length'
        length_nodes = [
            helper.make_node('Shape', ['attention_mask'], ['clair_mask_shape']),
            helper.make_node('Gather', ['clair_mask_shape', '/model/constants/INT64/[1]'], ['clair_length_vector']),
            helper.make_node('Reshape', ['clair_length_vector', 'clair_scalar_shape'], ['clair_length_i64']),
            helper.make_node('Cast', ['clair_length_i64'], ['clair_cache_length'], to=TensorProto.INT32),
        ]
        graph.initializer.append(helper.make_tensor('clair_scalar_shape', TensorProto.INT64, [0], []))
        first_attention = next(i for i, n in enumerate(graph.node) if n.op_type == 'GroupQueryAttention')
        for index, node in enumerate(length_nodes, first_attention):
            graph.node.insert(index, node)

    limit = 1536 * 1024**2
    shard = -1
    files = []
    writer = None
    try:
        with (source / 'model.onnx.data').open('rb') as weights:
            for tensor in graph.initializer:
                if not uses_external_data(tensor):
                    continue
                data = {value.key: value.value for value in tensor.external_data}
                length = int(data['length'])
                if length > limit:
                    raise ValueError(f'Tensor too large to shard: {tensor.name}')
                if writer is None or writer.tell() + length > limit:
                    if writer:
                        writer.close()
                    shard += 1
                    files.append(f'weights-{shard}.data')
                    writer = (output / (files[-1] + '.part')).open('wb')
                offset = writer.tell()
                weights.seek(int(data['offset']))
                remaining = length
                while remaining:
                    block = weights.read(min(remaining, 4 * 1024**2))
                    if not block:
                        raise ValueError(f'Unexpected end of weights for {tensor.name}')
                    writer.write(block)
                    remaining -= len(block)
                del tensor.external_data[:]
                for key, value in (('location', files[-1]), ('offset', str(offset)), ('length', str(length))):
                    item = tensor.external_data.add()
                    item.key, item.value = key, value
    finally:
        if writer:
            writer.close()
    for name in files:
        (output / (name + '.part')).replace(output / name)
    graph_file = output / 'model.onnx.part'
    graph_file.write_bytes(model.SerializeToString())
    graph_file.replace(output / 'model.onnx')
    profile = dict(id=args.model, name=args.model, vocabSize=model.graph.output[0].type.tensor_type.shape.dim[-1].dim_value,
                   eos=config['eos_token_id'], layers=decoder['num_hidden_layers'], heads=decoder['num_key_value_heads'],
                   headSize=decoder['head_size'], chat={'phi4-mini': 'phi4', 'qwen3-4b': 'qwen3'}.get(args.model, 'qwen'),
                   noPositionInput=not any(x.name == 'position_ids' for x in graph.input),
                   selectedLogits=True, weightFiles=files)
    (output / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
    print(json.dumps(profile))


if __name__ == '__main__':
    main()
