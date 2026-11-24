import {execFile} from 'node:child_process'
import {createServer} from 'node:http'
import {createReadStream, existsSync} from 'node:fs'
import {readdir, readFile, stat, writeFile} from 'node:fs/promises'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {promisify} from 'node:util'
import {chromium} from 'playwright'

const root = fileURLToPath(new URL('../../', import.meta.url))
const dist = path.join(root, 'web', 'dist', 'assets')
const comparison = process.env.CLAIR_CPU_COMPARISON_DIR
const output = comparison || path.join(root, 'data', 'webnn-bench')
const installedCandidate = path.join(root, 'data', 'webnn-model', 'qwen25-15b')
const candidates = {
  qwen2: {directory: path.join(root, 'data', 'webnn-model', 'qwen2'), profile: undefined},
  'qwen25-15b': {
    directory: existsSync(path.join(installedCandidate, 'model.onnx.data')) ? installedCandidate : path.join(output, 'qwen25-15b'),
    profile: {id: 'qwen25-15b', name: 'Qwen2.5 1.5B', layers: 28, heads: 2,
      headSize: 128, vocabSize: 151936, eos: [151643, 151645], chat: 'qwen', kvDimension: 'kv_cache_dim'},
  },
  'phi4-mini': {
    directory: path.join(output, 'phi4-mini'),
    profile: {id: 'phi4-mini', name: 'Phi-4 Mini', layers: 32, heads: 8,
      headSize: 128, vocabSize: 200064, eos: [199999, 200020], chat: 'phi4'},
  },
}
for (const id of ['qwen2.5-3b-instruct', 'qwen3-4b', 'phi4-mini']) {
  const directory = path.join(output, id)
  const graphDirectory = path.join(directory, 'webnn')
  const profilePath = path.join(graphDirectory, 'profile.json')
  if (existsSync(profilePath)) {
    candidates[id] = {directory, graphDirectory, profile: JSON.parse(await readFile(profilePath, 'utf8'))}
  }
}
if (comparison) {
  const {directory, profile} = JSON.parse(await readFile(path.join(output, 'model.json'), 'utf8'))
  candidates[profile.id] = {directory, graphDirectory: directory, profile}
}
const filter = process.env.CLAIR_BENCH_CASE?.split(',')
const tests = JSON.parse(await readFile(path.join(output, 'cases.json'), 'utf8'))
  .filter(test => !filter || filter.includes(test.id))
const assets = new Set(['model.onnx', 'model.onnx.data', 'tokenizer.json', 'tokenizer_config.json'])
const worker = (await readdir(dist)).find(file => /^webnn-worker-.+\.js$/.test(file))
if (!worker) throw new Error('Build the Clair frontend first.')

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  // The browser uses the real Clair worker. Its model assets are served from the
  // local benchmark directory, so the production library and cache are untouched.
  res.setHeader('Content-Security-Policy',
    "default-src 'self'; script-src 'self' 'unsafe-eval'; worker-src 'self'; connect-src 'self'")
  if (url.pathname === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8')
    return res.end('<title>Clair WebNN benchmark</title>')
  }
  const model = url.pathname.match(/^\/api\/webnn\/(?:models\/([\w.-]+)\/)?assets\/([\w.-]+)$/)
  const runtime = url.pathname.match(/^\/assets\/([\w.-]+)$/)
  let file
  if (model && Object.hasOwn(candidates, model[1] || 'qwen2')) {
    const candidate = candidates[model[1] || 'qwen2']
    if (candidate.graphDirectory && (model[2] === 'model.onnx' || candidate.profile.weightFiles.includes(model[2]))) {
      file = path.join(candidate.graphDirectory, model[2])
    } else if (assets.has(model[2])) {
      file = path.join(candidate.directory, model[2])
    }
  } else if (runtime) {
    file = path.join(dist, runtime[1])
  }
  try {
    const {size} = await stat(file)
    res.setHeader('Content-Length', size)
    res.setHeader('Content-Type', file.endsWith('.wasm') ? 'application/wasm' :
      /\.m?js$/.test(file) ? 'text/javascript' : 'application/octet-stream')
    const stream = createReadStream(file)
    res.on('close', () => stream.destroy())
    stream.on('error', () => res.destroy())
    stream.pipe(res)
  } catch {
    res.writeHead(404).end()
  }
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`

const selected = process.argv.slice(2)
const ids = selected.length ? selected : Object.keys(candidates)
const run = promisify(execFile)

async function memory(cdp, peaks) {
  const {processInfo} = await cdp.send('SystemInfo.getProcessInfo')
  const ids = processInfo.map(process=>Number(process.id)).filter(Number.isSafeInteger)
  if (!ids.length) return
  const {stdout} = await run('powershell.exe', ['-NoProfile', '-Command',
    `Get-Process -Id ${ids.join(',')} -ErrorAction SilentlyContinue | Select-Object WorkingSet64,PrivateMemorySize64 | ConvertTo-Json -Compress`],
    {windowsHide:true})
  const processes = [].concat(JSON.parse(stdout || '[]'))
  for (const [metric, field] of [['resident_peak_mib','WorkingSet64'], ['private_peak_mib','PrivateMemorySize64']]) {
    const mib = processes.reduce((sum, process)=>sum+process[field],0)/1048576
    peaks[metric] = Math.max(peaks[metric] ?? 0, mib)
  }
}

let browser
try {
  browser = await chromium.launch({channel: 'msedge', chromiumSandbox: true,
    args: ['--enable-features=WebMachineLearningNeuralNetwork']})
  const cdp = comparison ? await browser.newBrowserCDPSession() : null
  for (const id of ids) {
    if (!Object.hasOwn(candidates, id)) throw new Error(`Unknown model: ${id}`)
    const record = {model: id, browser: browser.version(), context: Number(process.env.CLAIR_BENCH_CONTEXT || 2048), results: []}
    const suffix = process.env.CLAIR_BENCH_TAG?.replace(/[^a-zA-Z0-9-]/g, '') || (filter ? 'selected' : '')
    const checkpoint = () => writeFile(path.join(output, `${id}${suffix ? '-' + suffix : ''}.json`), JSON.stringify(record, null, 2))
    for (const device of (process.env.CLAIR_BENCH_DEVICE ? [process.env.CLAIR_BENCH_DEVICE] : ['gpu', 'cpu'])) {
      const page = await browser.newPage()
      const external = []
      await page.route('**/*', route => {
        if (new URL(route.request().url()).origin === origin) return route.continue()
        external.push(route.request().url())
        return route.abort()
      })
      try {
        await page.goto(origin)
        console.log(`${id} ${device} starting`)
        for (const test of tests) {
          console.log(`${device} · ${test.id}`)
          const peaks = {}
          let collecting = true
          const monitor = cdp && (async () => {
            while (collecting) {
              try { await memory(cdp, peaks) }
              catch (error) { peaks.memory_sampling_error ??= error.message }
              if (collecting) await new Promise(resolve=>setTimeout(resolve,2000))
            }
          })()
          let result
          try {
            result = await page.evaluate(({url, data}) => new Promise(resolve => {
              const worker = window.clairWorker ??= new Worker(url, {type: 'module'})
              const start = performance.now(), states = []
              const finish = result => {
                clearTimeout(timer)
                worker.onmessage = worker.onerror = null
                resolve({...result, elapsed_ms: performance.now() - start, states})
              }
              const timer = setTimeout(() => finish({error: 'Timed out after 240 s'}), 240000)
              worker.onmessage = ({data}) => data.type === 'status' ? states.push(data.text) :
                finish(data.type === 'result' ? data.result : {error: data.message})
              worker.onerror = event => finish({error: event.message})
              worker.postMessage(data)
            }), {url: `/assets/${worker}`, data: {...test.request, device, context: record.context, model: candidates[id].profile}})
          } catch (error) {
            result = {error: error.message}
          } finally {
            collecting = false
            await monitor
          }
          record.results.push({device, test: test.id, ...result, ...peaks, external: [...external]})
          await checkpoint()
          console.log(`${id} ${device} ${test.id}: ${result.error || (result.elapsed_ms / 1000).toFixed(2) + ' s; ' + result.dispatches + ' appels WebNN'}`)
          if (result.error) break
        }
      } finally {
        await page.close()
      }
    }
  }
} finally {
  await browser?.close()
  server.close()
}
