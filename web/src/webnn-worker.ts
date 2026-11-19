/// <reference types="vite/client" />
import * as ort from 'onnxruntime-web/webgpu'
import wasm from 'onnxruntime-web/ort-wasm-simd-threaded.asyncify.wasm?url'
import wasmModule from 'onnxruntime-web/ort-wasm-simd-threaded.asyncify.mjs?url'
import {Tokenizer} from '@huggingface/tokenizers'

type TensorHandle = {destroy(): void}
type GpuContext = {
  createTensor(options: {dataType: string; shape: number[]; readable: boolean}): Promise<TensorHandle>
  readTensor(tensor: TensorHandle): Promise<ArrayBuffer>
  dispatch(...args: unknown[]): void
  destroy(): void
}
type Request = {
  messages: {role: string; content: string}[]
  context: number
  max_tokens: number
  json_output: boolean
  device: 'gpu' | 'cpu'
  model?: ModelProfile
}

export type ModelProfile = {
  id: string
  name: string
  vocabSize: number
  eos: number[]
  layers: number
  heads: number
  headSize: number
  chat: 'qwen' | 'qwen3' | 'phi4'
  kvDimension?: string
  noPositionInput?: boolean
  selectedLogits?: boolean
  weightFiles?: string[]
}
const defaultModel: ModelProfile = {
  id: '', name: 'Qwen2', vocabSize: 151936, eos: [151643, 151645],
  layers: 24, heads: 2, headSize: 64, chat: 'qwen',
}
const report = (text: string) => self.postMessage({type: 'status', text})
const gpu = (navigator as Navigator & {ml?: {createContext(options: {deviceType: string}): Promise<GpuContext>}}).ml
ort.env.wasm.numThreads = 1
ort.env.wasm.wasmPaths = {wasm, mjs: wasmModule}
let dispatches = 0
let runtime: Awaited<ReturnType<typeof load>> | undefined
let verified = false

self.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
  event.preventDefault()
  self.postMessage({type: 'error', message: String(event.reason)})
})

async function file(assets: string, name: string) {
  const response = await fetch(assets + name)
  if (!response.ok) throw Error('Modèle WebNN absent. Exécutez installer.bat.')
  return response
}

async function load(context: number, deviceType: Request['device'], model: ModelProfile) {
  if (!gpu) throw Error('WebNN est indisponible dans ce navigateur. Ouvrez Clair avec demarrer.bat.')
  report(`Chargement de ${model.name}…`)
  const assets = model.id ? `/api/webnn/models/${encodeURIComponent(model.id)}/assets/` : '/api/webnn/assets/'
  const ml = await gpu.createContext({deviceType})
  // Count actual WebNN dispatches. ORT can assign unsupported nodes to its CPU provider.
  const dispatch = ml.dispatch.bind(ml)
  ml.dispatch = (...args) => {dispatch(...args); dispatches++}
  let prefill: ort.InferenceSession | undefined
  try {
    const weightFiles = model.weightFiles ?? ['model.onnx.data']
    const [graph, weights, tokenizerData, tokenizerConfig] = await Promise.all([
      file(assets, 'model.onnx').then(r => r.arrayBuffer()),
      Promise.all(weightFiles.map(async path => ({path, data: await (await file(assets, path)).arrayBuffer()}))),
      file(assets, 'tokenizer.json').then(r => r.json()),
      file(assets, 'tokenizer_config.json').then(r => r.json()),
    ])
    const tokenizer = new Tokenizer(tokenizerData, tokenizerConfig)
    const options = (sequence: number): ort.InferenceSession.SessionOptions => ({
      executionProviders: [{name: 'webnn', deviceType, context: ml}] as ort.InferenceSession.SessionOptions['executionProviders'],
      externalData: weights,
      freeDimensionOverrides: {
        batch_size: 1,
        sequence_length: sequence,
        total_sequence_length: context,
        past_sequence_length: context,
        ...(model.kvDimension ? {[model.kvDimension]: model.headSize} : {}),
      },
    })
    report(`Compilation du modèle avec WebNN (${deviceType.toUpperCase()})…`)
    prefill = await ort.InferenceSession.create(graph, options(context))
    const decode = await ort.InferenceSession.create(graph, options(1))
    return {ml, prefill, decode, tokenizer, context, deviceType, modelId: model.id}
  } catch (error) {
    try {await prefill?.release()} finally {ml.destroy()}
    throw error
  }
}

function selectToken(logits: Float16Array, offset: number, repetition: Set<number>, vocabSize: number) {
  let best = -Infinity
  let token = 0
  for (let i = 0; i < vocabSize; i++) {
    let logit = logits[offset + i]
    if (repetition.has(i)) logit = logit > 0 ? logit / 1.16 : logit * 1.16
    if (logit <= best || !Number.isFinite(logit)) continue
    best = logit
    token = i
  }
  if (!Number.isFinite(best)) throw Error('Le modèle a renvoyé des scores non valides.')
  return token
}

async function generate({messages, context, max_tokens, json_output, device, model = defaultModel}: Request, checking = false) {
  const started = performance.now()
  runtime ??= await load(context, device, model)
  const {ml, prefill, decode, tokenizer} = runtime
  if (runtime.context !== context || runtime.modelId !== model.id || runtime.deviceType !== device)
    throw Error('Le modèle ou son contexte a changé. Rechargez la page.')
  const ready = performance.now()
  const {vocabSize, layers, heads, headSize} = model
  const eos = new Set(model.eos)
  const framing = model.chat === 'phi4'
    ? messages.map(m => `<|${m.role}|>${m.content.replaceAll('<|', '‹|')}<|end|>`).join('') + '<|assistant|>'
    : messages.map(m => `<|im_start|>${m.role}\n${m.content.replaceAll('<|', '‹|')}<|im_end|>\n`).join('')
      + '<|im_start|>assistant\n' + (model.chat === 'qwen3' ? '<think>\n\n</think>\n\n' : '')
  const prompt = tokenizer.encode(framing).ids
  if (!prompt.length || prompt.length + max_tokens > context) throw Error('Le texte dépasse le contexte WebNN.')
  const input: Record<string, ort.Tensor> = {}
  const output: Record<string, ort.Tensor> = {}
  const tensors: TensorHandle[] = []
  const values = async (shape: number[], readable = false) => {
    const handle = await ml.createTensor({dataType: 'float16', shape, readable})
    tensors.push(handle)
    return ort.Tensor.fromMLTensor(handle as never, {dataType: 'float16', dims: shape})
  }
  const int64 = (data: BigInt64Array) => new ort.Tensor('int64', data, [1, data.length])
  const mask = new BigInt64Array(context)
  const ids = new BigInt64Array(context)
  const positions = new BigInt64Array(context)
  prompt.forEach((token, i) => {ids[i] = BigInt(token); positions[i] = BigInt(i); mask[i] = 1n})
  const cache = Array.from({length: layers}, (_, i) => [`${i}.key`, `${i}.value`]).flat()
  const generated: number[] = []
  const repetition = new Set<number>()
  const text = () => tokenizer.decode(generated, {skip_special_tokens: true})
  let completeJson = ''
  const before = dispatches
  try {
    if (!checking) report('WebNN lit les passages sources…')
    for (const key of cache) {
      input['past_key_values.' + key] = await values([1, heads, context, headSize])
      output['present.' + key] = await values([1, heads, context, headSize])
    }
    const promptLogits = await values([1, model.selectedLogits ? 1 : context, vocabSize], true)
    output.logits = promptLogits
    const swapCache = () => {
      for (const key of cache) {
        const past = 'past_key_values.' + key
        const present = 'present.' + key
        const previous = input[past] as ort.Tensor
        input[past] = output[present]
        output[present] = previous
      }
    }
    input.input_ids = int64(ids)
    input.attention_mask = int64(mask)
    if (!model.noPositionInput) input.position_ids = int64(positions)
    const logitsIndex = (index: number) => new ort.Tensor('int64', BigInt64Array.of(BigInt(index)), [])
    if (model.selectedLogits) input.clair_logits_index = logitsIndex(prompt.length - 1)
    await prefill.run(input, output)
    const scores = new Float16Array(await ml.readTensor(promptLogits.mlTensor as TensorHandle))
    let next = selectToken(scores, model.selectedLogits ? 0 : (prompt.length - 1) * vocabSize, repetition, vocabSize)
    swapCache()
    const first = performance.now()
    output.logits = await values([1, 1, vocabSize], true)
    if (model.selectedLogits) input.clair_logits_index = logitsIndex(0)
    if (!checking) report('WebNN rédige la réponse…')
    while (!eos.has(next) && generated.length < max_tokens) {
      generated.push(next)
      repetition.add(next)
      if (json_output && generated.length % 4 === 0) {
        const value = text().trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
        if (/^[{\[]/.test(value) && /[}\]]$/.test(value)) {
          try {
            JSON.parse(value)
            completeJson = value
            break
          } catch {}
        }
      }
      if (generated.length === max_tokens) break
      const position = prompt.length + generated.length - 1
      mask[position] = 1n
      input.input_ids = int64(BigInt64Array.of(BigInt(next)))
      input.attention_mask = int64(mask)
      if (!model.noPositionInput) input.position_ids = int64(BigInt64Array.of(BigInt(position)))
      await decode.run(input, output)
      next = selectToken(new Float16Array(await ml.readTensor(output.logits.mlTensor as TensorHandle)), 0, repetition, vocabSize)
      swapCache()
    }
    if (dispatches === before) throw Error('Aucun calcul du modèle n’a été exécuté par WebNN.')
    return {
      text: completeJson || text(),
      device,
      done_reason: completeJson || eos.has(next) ? 'stop' : 'length',
      prompt_tokens: prompt.length,
      output_tokens: generated.length,
      dispatches: dispatches - before,
      load_ms: ready - started,
      prompt_evaluation_ms: first - ready,
      output_generation_ms: performance.now() - first,
    }
  } finally {
    for (const tensor of tensors) tensor.destroy()
  }
}

self.onmessage = async ({data}: MessageEvent<Request>) => {
  try {
    let gpuCheckMs = 0
    if (data.device === 'gpu' && !verified) {
      const started = performance.now()
      report('Vérification du modèle sur le GPU…')
      const check = await generate({...data,
        messages: [{role: 'user', content: 'Count from 1 to 10. Only write the numbers.'}],
        max_tokens: 56, json_output: false,
      }, true)
      if (check.text.match(/\d+/g)?.join(' ') !== '1 2 3 4 5 6 7 8 9 10') {
        throw Error('Le test de génération du GPU a échoué.')
      }
      verified = true
      gpuCheckMs = performance.now() - started
    }
    const result = await generate(data)
    self.postMessage({type: 'result', result: {...result, gpu_check_ms: gpuCheckMs}})
  } catch (error) {
    self.postMessage({type: 'error', message: error instanceof Error ? error.message : String(error)})
  }
}
