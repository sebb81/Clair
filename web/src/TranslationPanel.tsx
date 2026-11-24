import {useEffect, useRef, useState} from 'react'
import {Download, Languages, LoaderCircle, Square} from 'lucide-react'
import {deviceLabels,generateInBrowser,releaseBrowserModel,type DeviceReport,type DeviceSelection} from './browser-generation'

type Pair = {source:string;target:string;installed:boolean}
type Translation = {id:string;language:string;language_name:string;model:string;model_name?:string;engine?:string;source_language?:string|null;status:string;total:number;completed:number;warnings:string[];error:string;devices?:{device:string;blocks:number}[]}
type TranslationOptions = {languages:Record<string,string>;bergamot_pairs?:Pair[];translations:Translation[]}

type Props = {docId:string;model:string;modelName:string;device:DeviceSelection;onDeviceReport:(report:DeviceReport|null)=>void;ready:boolean;busy:boolean;onBusyChange:(busy:boolean)=>void}
async function responseJson(response:Response):Promise<TranslationOptions> {
  const value = await response.json()
  if (!response.ok) throw Error(value.detail || 'Erreur de traduction locale.')
  return value
}

export function TranslationPanel({docId,model,modelName,device,onDeviceReport,ready,busy,onBusyChange}:Props) {
  const [engine,setEngine] = useState<'webnn'|'bergamot'>('webnn')
  const [sourceLanguage,setSourceLanguage] = useState('fr')
  const [language,setLanguage] = useState('en')
  const [languages,setLanguages] = useState<Record<string,string>>({})
  const [pairs,setPairs] = useState<Pair[]>([])
  const [jobs,setJobs] = useState<Translation[]>([])
  const [status,setStatus] = useState('')
  const [error,setError] = useState('')
  const controller = useRef<AbortController|null>(null)
  const native = engine==='bergamot'
  const pair = pairs.find(option=>option.source===sourceLanguage)
  const target = native ? pair?.target : language
  const available = native ? !!pair?.installed : ready
  const current = jobs.find(job=>job.language===target && (
    native ? job.engine==='bergamot' && job.source_language===sourceLanguage : job.model===model
  ))
  const download = (job:Translation) => `/api/documents/${docId}/translations/${job.id}/download`

  function applyOptions(result:TranslationOptions) {
    setLanguages(result.languages)
    setPairs(result.bergamot_pairs || [])
    setJobs(result.translations)
  }
  async function refresh() {
    applyOptions(await responseJson(await fetch(`/api/documents/${docId}/translations`)))
  }
  useEffect(()=>{
    let active = true
    fetch(`/api/documents/${docId}/translations`).then(responseJson).then(result=>{
      if (active) applyOptions(result)
    }).catch(e=>{if(active)setError(String(e))})
    return ()=>{active=false;controller.current?.abort()}
  },[docId])

  async function translate() {
    if (busy || !available || !target) return
    const abort = new AbortController()
    controller.current = abort
    onBusyChange(true)
    onDeviceReport(null)
    setError('')
    setStatus('Préparation du texte à traduire…')
    let complete = false
    async function event(item:any) {
      if (item.type==='error') throw Error(item.message)
      if (item.type==='status') setStatus(item.text)
      if (item.type==='generate') onDeviceReport(await generateInBrowser(item,abort.signal,setStatus,device))
      if (item.type==='translation_progress' || item.type==='translation_done') {
        setJobs(old=>[item.translation,...old.filter(job=>job.id!==item.translation.id)])
        if (item.type==='translation_done') {complete=true;setStatus('Traduction terminée.')}
      }
    }
    try {
      const response = await fetch(`/api/documents/${docId}/translate`,{
        method:'POST',headers:{'Content-Type':'application/json'},signal:abort.signal,
        body:JSON.stringify(native ? {engine,language:target,source_language:sourceLanguage}
          : {language,model,webnn_device:device}),
      })
      if (!response.ok) await responseJson(response)
      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      try {
        while (true) {
          const {value,done} = await reader.read()
          buffer += decoder.decode(value,{stream:!done})
          const lines = buffer.split('\n')
          buffer = lines.pop()!
          for (const line of lines) if(line.trim()) await event(JSON.parse(line))
          if (done) {if(buffer.trim())await event(JSON.parse(buffer));break}
        }
      } finally {await reader.cancel()}
      if (!complete) throw Error('Traduction interrompue avant la fin. Vous pouvez la reprendre.')
    } catch(e) {
      if (abort.signal.aborted) setStatus('Traduction arrêtée. Les blocs terminés sont conservés.')
      else {setError(String(e).replace(/^Error: /,''));setStatus('')}
    } finally {
      if (!native) await releaseBrowserModel()
      controller.current = null
      onBusyChange(false)
      await refresh().catch(e=>setError(String(e)))
    }
  }

  return <section className="translation-panel" aria-labelledby="translation-title">
    <div className="translation-title"><Languages size={24}/><h2 id="translation-title">Traduire le document</h2></div>
    <p>Tout le texte extrait sera traduit dans l’ordre, avec des repères de pages ou de blocs.</p>
    <div className="translation-controls">
      {!!pairs.length&&<label>Moteur de traduction<select value={engine} onChange={e=>{
        setEngine(e.target.value==='bergamot'?'bergamot':'webnn');setStatus('');setError('')
      }} disabled={busy}>
        <option value="webnn">WebNN</option>
        <option value="bergamot">Bergamot (CPU)</option>
      </select></label>}
      {native?<label>Sens de traduction<select value={sourceLanguage} onChange={e=>{
        setSourceLanguage(e.target.value);setStatus('');setError('')
      }} disabled={busy}>
        {pairs.map(option=><option key={option.source} value={option.source}>
          {languages[option.source]} → {languages[option.target]}
        </option>)}
      </select></label>:<label>Langue de traduction<select value={language} onChange={e=>{setLanguage(e.target.value);setStatus('');setError('')}} disabled={busy}>
        {Object.entries(languages).map(([key,name])=><option key={key} value={key}>{name}</option>)}
      </select></label>}
      {busy?<button className="translation-start" onClick={()=>controller.current?.abort()}><Square size={15}/> Arrêter la traduction</button>
        :<button className="translation-start" disabled={!available || !target || !languages[target] || current?.status==='complete'} onClick={translate}>
          <Languages size={17}/>{current?.status==='complete'?'Traduction terminée':current && current.completed>0?'Reprendre la traduction':'Traduire le document'}
        </button>}
    </div>
    {!native&&<p className="translation-runtime">{modelName || 'Choisissez un modèle dans les paramètres'} · {deviceLabels[device]}. La langue d’origine est détectée par le modèle.</p>}
    {!native&&!!current?.devices?.length&&<p className="translation-runtime">Contextes des blocs déjà calculés : {current.devices.map(item=>`${item.device.toUpperCase()} (${item.blocks})`).join(', ')}. Ces blocs sont conservés à la reprise.</p>}
    {!available&&<p className="warning">{native?'Lancez installer-traduction.bat, puis rechargez Clair.'
      :'Ouvrez Clair avec demarrer.bat et sélectionnez un modèle WebNN installé.'}</p>}
    {error&&<p role="alert" className="translation-error">{error}</p>}
    <div aria-live="polite" className="translation-progress">
      {current&&<><b>{current.completed} / {current.total} blocs traduits</b><progress aria-label="Progression de la traduction" value={current.completed} max={Math.max(1,current.total)}/></>}
      {status&&<p>{busy&&<LoaderCircle size={15} className="spin"/>}{status}</p>}
      {current?.status==='error'&&!error&&<p className="translation-error">{current.error}</p>}
    </div>
    {current?.status==='complete'&&<a className="translation-download" href={download(current)} download><Download size={18}/> Télécharger la traduction en DOCX</a>}
    <p className="translation-limit">Les blocs terminés sont sauvegardés : vous pouvez arrêter puis reprendre avec la même langue et le même modèle. Les images et la mise en page originale ne sont pas reproduites. Les scans nécessitent un OCR avant importation.</p>
    <p className="translation-limit">Traduction automatique à relire. Tous les blocs parcourus ne signifient pas que chaque phrase est fidèlement traduite.</p>
    {current?.warnings.length ? <details className="translation-notes"><summary>Portée de cette traduction</summary>{current.warnings.map((warning,i)=><p key={i}>{warning}</p>)}</details>:null}
    {jobs.some(job=>job.status==='complete'&&job.id!==current?.id)&&<details className="translation-history"><summary>Autres traductions disponibles</summary>{jobs.filter(job=>job.status==='complete'&&job.id!==current?.id).map(job=><a key={job.id} href={download(job)} download>{job.language_name} · {job.model_name || job.model} <Download size={14}/></a>)}</details>}
  </section>
}
