import {Wllama,type ChatCompletionChunk,type WllamaChatMessage} from '@wllama/wllama'
import wasm from '@wllama/wllama/esm/wasm/wllama.wasm?url'

export type WllamaRequest = {
  id:string
  context:number
  max_tokens:number
  model_url:string
  messages:WllamaChatMessage[]
  schema:Record<string,unknown>|null
}

let engine:Wllama|undefined
let running:AbortController|undefined

const status=(text:string)=>self.postMessage({type:'status',text})

async function generate(request:WllamaRequest, signal:AbortSignal) {
  const started=performance.now()
  let loadMs=0
  if (!engine) {
    status('Wllama charge le modèle GGUF local…')
    engine=new Wllama({default:wasm},{suppressNativeLog:true})
    engine.setCompat(null)
    let lastPercent=-1
    await engine.loadModelFromUrl(new URL(request.model_url,self.location.origin).href,{
      n_ctx:request.context, n_threads:Math.min(8,navigator.hardwareConcurrency||1),
      n_gpu_layers:0, offload_kqv:false, n_parallel:1, ctx_shift:false, warmup:false,
      signal, retries:0,
      progressCallback:({loaded,total})=>{
        const percent=total ? Math.floor(100*loaded/total) : 0
        if (percent!==lastPercent) status(`Copie locale du modèle Wllama… ${percent} %`)
        lastPercent=percent
      },
    })
    loadMs=performance.now()-started
  }
  signal.throwIfAborted()
  status('Wllama lit les passages et rédige sur CPU…')
  const chunks=await engine.createChatCompletion({
    messages:request.messages.map(message=>({...message,content:message.content.replaceAll('<|','‹|')})),
    chat_template_kwargs:{enable_thinking:false},
    max_tokens:request.max_tokens, temperature:0, penalty_repeat:1.16, penalty_last_n:request.max_tokens,
    cache_prompt:false, stream:true, abortSignal:signal,
    ...(request.schema ? {response_format:{type:'json_schema',json_schema:{name:'clair_summary',schema:request.schema}}} : {}),
  })
  let text=''
  let finish=null
  let timing:ChatCompletionChunk['timings']
  let usage:ChatCompletionChunk['usage']
  for await (const chunk of chunks) {
    const choice=chunk.choices[0]
    text+=choice?.delta.content??''
    finish=choice?.finish_reason??finish
    timing=chunk.timings??timing
    usage=chunk.usage??usage
  }
  signal.throwIfAborted()
  if (!text.trim()||(finish!=='stop'&&finish!=='length')) throw Error('Wllama a interrompu la réponse.')
  return {
    text, done_reason:finish, context_tokens:request.context, threads:engine.getNumThreads(),
    prompt_tokens:timing?.prompt_n??usage?.prompt_tokens??0, output_tokens:timing?.predicted_n??usage?.completion_tokens??0,
    load_ms:loadMs, generation_ms:performance.now()-started,
    prompt_evaluation_ms:timing?.prompt_ms??0, output_generation_ms:timing?.predicted_ms??0,
  }
}

self.onmessage=async ({data}:MessageEvent<(WllamaRequest & {type:'generate'})|{type:'release'}>)=>{
  if (data.type==='release') {
    running?.abort()
    const current=engine
    engine=undefined
    try {await current?.exit()} finally {self.postMessage({type:'released'})}
    return
  }
  running=new AbortController()
  try {self.postMessage({type:'result',result:await generate(data,running.signal)})}
  catch (error) {
    const message=error instanceof Error?error.message:String(error)
    const quota=(error instanceof Error&&error.name==='QuotaExceededError')||message.includes('No space available')
    self.postMessage({type:'error',message:quota?
      'Espace insuffisant dans le cache Wllama. Utilisez un profil Edge normal avec environ 2,5 Go disponibles.':message})
  }
  finally {running=undefined}
}
