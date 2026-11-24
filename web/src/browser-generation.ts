import type {ModelProfile} from './webnn-worker'

export type Device = 'cpu' | 'gpu' | 'npu'
export type DeviceSelection = 'auto' | Device
export type DeviceAttempt = {device:Device;status:'failed'|'skipped'|'used';duration_ms:number;error?:string}
export type DeviceReport = {preference:DeviceSelection;device:Device;attempts:DeviceAttempt[];dispatches:number}
export const deviceLabels:Record<DeviceSelection,string> = {
  auto:'Automatique (NPU → GPU → CPU)',npu:'NPU prioritaire',gpu:'GPU prioritaire',cpu:'CPU uniquement',
}
export function storedDevice():DeviceSelection {
  const stored=localStorage.getItem('clair-webnn-device')
  return stored==='cpu'||stored==='gpu'||stored==='npu'?stored:'auto'
}
type Generation = {
  id:string; messages:{role:string;content:string}[]
  context:number; max_tokens:number; json_output:boolean; model:ModelProfile|null
}
let worker:Worker|undefined
let workerModel:string|undefined
let releasing:Promise<void>=Promise.resolve()
let idleTimer:ReturnType<typeof setTimeout>|undefined
const checkPrefix='clair-webnn-device-v2:'

export function releaseBrowserModel() {
  clearTimeout(idleTimer)
  const current=worker
  worker=undefined
  workerModel=undefined
  if(!current)return releasing
  // Terminating a worker alone leaves cleanup to the browser. Explicitly release
  // ORT sessions and MLContext first, including between failed device attempts.
  releasing=new Promise<void>(resolve=>{
    const finish=()=>{clearTimeout(timer);current.onmessage=null;current.onerror=null;current.terminate();resolve()}
    const timer=setTimeout(finish,2000)
    current.onmessage=({data})=>{if(data.type==='released')finish()}
    current.onerror=finish
    try {current.postMessage({type:'release'})} catch {finish()}
  })
  return releasing
}
export function scheduleBrowserModelRelease() {
  clearTimeout(idleTimer)
  idleTimer=setTimeout(()=>{void releaseBrowserModel()},30000)
}
export function resetDeviceChecks() {
  releaseBrowserModel()
  for(const key of Object.keys(sessionStorage)) if(key.startsWith(checkPrefix))sessionStorage.removeItem(key)
}
function plan(preference:DeviceSelection):Device[] {
  if(preference==='cpu')return ['cpu']
  if(preference==='gpu')return ['gpu','npu','cpu']
  return ['npu','gpu','cpu']
}

async function run(request:Generation,device:Device,signal:AbortSignal,status:(text:string)=>void,timeout:number) {
  await releasing
  signal.throwIfAborted()
  return new Promise<Record<string,any>>((resolve,reject)=>{
    worker??=new Worker(new URL('./webnn-worker.ts',import.meta.url),{type:'module'})
    const current=worker
    let timer:ReturnType<typeof setTimeout>
    const cleanup=()=>{
      clearTimeout(timer)
      current.onmessage=null
      current.onerror=null
      signal.removeEventListener('abort',abort)
    }
    const fail=(error:string)=>{cleanup();releaseBrowserModel();resolve({error})}
    const abort=()=>{cleanup();releaseBrowserModel();reject(signal.reason)}
    current.onmessage=({data})=>{
      if(data.type==='status')return status(data.text)
      cleanup()
      if(data.type==='error'){releaseBrowserModel();resolve({error:data.message})}
      else resolve(data.result)
    }
    current.onerror=event=>fail(event.message||'Échec de démarrage du moteur WebNN.')
    signal.addEventListener('abort',abort,{once:true})
    timer=setTimeout(()=>fail(`Le calcul WebNN ${device.toUpperCase()} dépasse le délai autorisé.`),timeout)
    current.postMessage({...request,model:request.model??undefined,device})
  })
}

export async function generateInBrowser(request:Generation,signal:AbortSignal,status:(text:string)=>void,
                                        preference:DeviceSelection):Promise<DeviceReport> {
  // Cache failed compilations per model and context, so long jobs do not retry every block.
  clearTimeout(idleTimer)
  const signature=JSON.stringify([request.model,request.context])
  const attempts:DeviceAttempt[]=[]
  const started=performance.now()
  let result:Record<string,any>={error:'Aucun périphérique WebNN disponible.'}
  let selected:Device='cpu'
  for(const device of plan(preference)) {
    signal.throwIfAborted()
    const checkKey=checkPrefix+signature+':'+device
    const failure=device!=='cpu'?sessionStorage.getItem(checkKey):null
    if(failure){attempts.push({device,status:'skipped',duration_ms:0,error:failure});continue}
    const runtime=signature+':'+device
    if(workerModel!==runtime){await releaseBrowserModel();workerModel=runtime}
    const attemptStart=performance.now()
    const remaining=880000-(attemptStart-started)
    if(remaining<=0){result={error:'Délai global du calcul WebNN dépassé.'};break}
    status(`Essai WebNN sur ${device.toUpperCase()}…`)
    result=await run(request,device,signal,status,Math.min(remaining,device==='cpu'?880000:120000))
    signal.throwIfAborted()
    if(!result.error&&(!result.dispatches||result.device!==device))
      result={error:'Le moteur n’a pas confirmé une exécution WebNN pour ce contexte.'}
    if(result.error){
      const error=String(result.error).slice(0,2000)
      attempts.push({device,status:'failed',duration_ms:performance.now()-attemptStart,error})
      if(device!=='cpu')sessionStorage.setItem(checkKey,error)
      await releaseBrowserModel()
      status(`${device.toUpperCase()} indisponible ou incompatible avec ce modèle. Essai du périphérique suivant…`)
      continue
    }
    selected=device
    attempts.push({device,status:'used',duration_ms:performance.now()-attemptStart})
    break
  }
  const report:DeviceReport={preference,device:selected,attempts,dispatches:result.dispatches??0}
  result={...result,device_preference:preference,device_attempts:attempts,
          device_verification:'webnn-context-and-generation',hardware_identity_verified:false}
  const response=await fetch('/api/webnn/results/'+request.id,{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(result),signal,
  })
  if(!response.ok)throw Error('Le calcul WebNN a été interrompu.')
  if(result.error)throw Error(attempts.map(a=>`${a.device.toUpperCase()} : ${a.error}`).join(' · ')||result.error)
  status(`Génération WebNN validée avec le contexte ${selected.toUpperCase()}.`)
  return report
}
