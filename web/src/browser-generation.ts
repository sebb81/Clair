import type {ModelProfile} from './webnn-worker'

export type DeviceSelection = 'auto' | 'cpu'
type Generation = {
  id: string; messages: {role: string; content: string}[]
  context: number; max_tokens: number; json_output: boolean
  model: ModelProfile | null
}
let worker: Worker | undefined
let workerModel: string | undefined

export function releaseBrowserModel() {
  worker?.terminate()
  worker = undefined
  workerModel = undefined
}

function run(request: Generation, device: 'gpu' | 'cpu', signal: AbortSignal, status: (text: string) => void) {
  signal.throwIfAborted()
  return new Promise<Record<string, unknown>>((resolve, reject) => {
    worker ??= new Worker(new URL('./webnn-worker.ts', import.meta.url), {type: 'module'})
    const current = worker
    const cleanup = () => {
      current.onmessage = null
      current.onerror = null
      signal.removeEventListener('abort', abort)
    }
    const abort = () => {
      cleanup()
      current.terminate()
      worker = undefined
      reject(signal.reason)
    }
    current.onmessage = ({data}) => {
      if (data.type === 'status') return status(data.text)
      cleanup()
      if (data.type === 'error') {
        current.terminate()
        worker = undefined
      }
      resolve(data.type === 'result' ? data.result : {error: data.message})
    }
    current.onerror = (event) => {
      cleanup()
      current.terminate()
      worker = undefined
      resolve({error: event.message || 'Échec de démarrage du moteur WebNN.'})
    }
    signal.addEventListener('abort', abort, {once: true})
    current.postMessage({...request, model: request.model ?? undefined, device})
  })
}

export async function generateInBrowser(request: Generation, signal: AbortSignal, status: (text: string) => void,
                                        preference: DeviceSelection) {
  const model = request.model?.id || ''
  const gpuCheck = model ? `clair-webnn-gpu-check:${model}` : 'clair-webnn-gpu-check'
  const device = preference === 'cpu' || sessionStorage.getItem(gpuCheck) === 'failed' ? 'cpu' : 'gpu'
  const runtime = model + ':' + device
  if (workerModel !== runtime) {
    worker?.terminate()
    worker = undefined
    workerModel = runtime
  }
  const started = performance.now()
  let result = await run(request, device, signal, status)
  if (result.error && device === 'gpu') {
    sessionStorage.setItem(gpuCheck, 'failed')
    workerModel = model + ':cpu'
    status('GPU WebNN non validé. Nouvelle tentative avec WebNN sur CPU…')
    const failedGpuMs = performance.now() - started
    result = {...await run(request, 'cpu', signal, status), gpu_fallback_ms: failedGpuMs}
  }
  signal.throwIfAborted()
  const response = await fetch('/api/webnn/results/' + request.id, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(result),
    signal,
  })
  if (!response.ok) throw Error('Le calcul WebNN a été interrompu.')
}
