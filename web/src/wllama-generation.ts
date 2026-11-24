import type {WllamaRequest} from './wllama-worker'

let worker:Worker|undefined
let releasing=Promise.resolve()

export function releaseWllama() {
  const current=worker
  if (!current) return releasing
  worker=undefined
  releasing=new Promise<void>(resolve=>{
    const finish=()=>{clearTimeout(timer);current.terminate();resolve()}
    const timer=setTimeout(finish,2500)
    current.onmessage=({data})=>{if(data.type==='released')finish()}
    current.onerror=finish
    try {current.postMessage({type:'release'})} catch {finish()}
  })
  return releasing
}

export async function generateWithWllama(request:WllamaRequest, signal:AbortSignal, status:(text:string)=>void) {
  await releasing
  signal.throwIfAborted()
  const result=await new Promise<Record<string,unknown>>((resolve,reject)=>{
    worker??=new Worker(new URL('./wllama-worker.ts',import.meta.url),{type:'module'})
    const current=worker
    const cleanup=()=>{
      clearTimeout(timer)
      current.onmessage=null
      current.onerror=null
      signal.removeEventListener('abort',abort)
    }
    const abort=()=>{cleanup();void releaseWllama();reject(signal.reason)}
    const fail=(error:string)=>{cleanup();void releaseWllama();resolve({error:error.slice(0,2000)})}
    const timer=setTimeout(()=>fail('Le calcul Wllama dépasse le délai autorisé.'),880000)
    signal.addEventListener('abort',abort,{once:true})
    current.onerror=event=>fail(event.message||'Wllama ne démarre pas dans ce navigateur.')
    current.onmessage=({data})=>{
      if (data.type==='status') status(data.text)
      if (data.type==='error') fail(data.message)
      if (data.type==='result') {cleanup();resolve(data.result)}
    }
    current.postMessage({...request,type:'generate'})
  })
  signal.throwIfAborted()
  const response=await fetch('/api/wllama/results/'+request.id,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(result),signal,
  })
  if (!response.ok) throw Error('Le calcul Wllama a été interrompu.')
}
