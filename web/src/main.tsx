import React, {useEffect, useRef, useState} from 'react'
import {createRoot} from 'react-dom/client'
import Markdown from 'react-markdown'
import {ArrowUp, BookOpen, Check, ChevronRight, FileText, FolderOpen, Layers, LoaderCircle, LockKeyhole, MessageSquare, Plus, Search, ShieldCheck, SlidersHorizontal, Square, Trash2, Upload, X} from 'lucide-react'
import './style.css'
import './translation.css'
import {deviceLabels,generateInBrowser,releaseBrowserModel,scheduleBrowserModelRelease,resetDeviceChecks,storedDevice,type DeviceReport,type DeviceSelection} from './browser-generation'
import {TranslationPanel} from './TranslationPanel'
import {DeviceStatus} from './DeviceStatus'
import {generateWithWllama,releaseWllama} from './wllama-generation'

type Source = {id:number;page:number|null;title:string;text:string;section:number}
type Message = {question:string;answer:string;sources:Source[];metrics:Record<string,any>;warnings?:string[]}
type Doc = {id:string;name:string;kind:string;pages:number;chars:number;chunks:number;warnings:string[];extraction_ms:number;summaries_cached:number;sections:{id:number;title:string;page:number}[]}
type WebNNModel = {model:string;name:string;context:number;installed:boolean}
type Health = {webnn_models:WebNNModel[];llamacpp_model?:WebNNModel;wllama_model?:WebNNModel;recommended_model:string|null;busy:boolean;max_upload_mb:number}
async function api(path:string, options?:RequestInit) {const r=await fetch('/api'+path,options);if(!r.ok){const e=await r.json().catch(()=>({detail:r.statusText}));throw Error(e.detail||'Erreur locale')}return r.json()}
const post=(body:unknown)=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
const quick=[['Résumé','Fais-moi un résumé structuré de ce document.'],['Points clés','Quels sont les points importants ?'],['Risques','Quels sont les risques identifiés ?'],['Décisions','Quelles sont les décisions prises ?']]
const modelPreferenceKey = 'clair-webnn-model'

function App(){
 const [health,setHealth]=useState<Health|null>(null)
 const [modelPreference,setModelPreference]=useState(()=>localStorage.getItem(modelPreferenceKey) ?? '')
 const [docs,setDocs]=useState<Doc[]>([]),[doc,setDoc]=useState<Doc|null>(null),[messages,setMessages]=useState<Message[]>([])
 const [device,setDevice]=useState<DeviceSelection>(storedDevice)
 const [deviceReport,setDeviceReport]=useState<DeviceReport|null>(null)
 const [question,setQuestion]=useState(''),[strategy,setStrategy]=useState('auto'),[format,setFormat]=useState('réponse détaillée')
 const [busy,setBusy]=useState(false),[uploading,setUploading]=useState(false),[status,setStatus]=useState(''),[error,setError]=useState('')
 const [source,setSource]=useState<{title:string;text:string;page:number;physical_page:boolean;tables:any[]}|null>(null)
 const [settings,setSettings]=useState(false),[drag,setDrag]=useState(false)
 const [mode,setMode]=useState<'chat'|'translate'>('chat')
 const input=useRef<HTMLInputElement>(null), abort=useRef<AbortController|null>(null), end=useRef<HTMLDivElement>(null)
 async function refresh(){try{const h=await api('/health');setHealth(h);setDocs(await api('/documents'))}catch(e){setError(String(e))}}
 useEffect(()=>{refresh();const t=setInterval(refresh,10000);return()=>clearInterval(t)},[])
 useEffect(()=>{localStorage.setItem(modelPreferenceKey,modelPreference)},[modelPreference])
 useEffect(()=>{localStorage.setItem('clair-webnn-device',device)},[device])
 useEffect(()=>{setDeviceReport(null)},[modelPreference,device])
 useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth',block:'end'})},[messages,status])
 async function select(id:string){
   if (busy) return
   setSource(null)
   setError('')
   try {
     const [nextDoc,nextMessages]=await Promise.all([api(`/documents/${id}`),api(`/documents/${id}/messages`)])
     setDoc(nextDoc)
     setMessages(nextMessages)
   } catch(e) {setError(String(e))}
 }
 async function upload(file?:File){if(!file||busy||uploading)return;setUploading(true);setError('');try{const form=new FormData();form.append('file',file);const r=await api('/documents',{method:'POST',body:form});await refresh();await select(r.document.id);setStatus(r.cached?'Extraction déjà en cache.':'Document prêt à être consulté.')}catch(e){setError(String(e))}finally{setUploading(false);if(input.current)input.current.value=''}}
 async function demo(){setUploading(true);try{const r=await api('/demo',{method:'POST'});await refresh();await select(r.document.id)}catch(e){setError(String(e))}finally{setUploading(false)}}
 async function showSource(id:number){if(!doc)return;try{const s=await api(`/documents/${doc.id}/sources/${id}`);const p=await api(`/documents/${doc.id}/pages/${s.page||s.block}`);setSource({title:s.title,text:s.text,page:s.page||s.block,physical_page:p.physical_page,tables:p.tables})}catch(e){setError(String(e))}}
 async function showPage(page:number,title:string){if(!doc)return;try{const p=await api(`/documents/${doc.id}/pages/${page}`);setSource({...p,title,page})}catch(e){setError(String(e))}}
 const webnnModels = health?.webnn_models ?? []
 const hasWebNN = typeof (navigator as Navigator & {ml?: unknown}).ml !== 'undefined'
 const nativeModel = health?.llamacpp_model
 const wasmModel = health?.wllama_model
 const preferredModel = [nativeModel,wasmModel,...webnnModels].some(item=>item?.model===modelPreference) ? modelPreference : ''
 const automaticModel = health?.recommended_model ?? ''
 const model = preferredModel || automaticModel
 const selectedWebNN = webnnModels.find(m => m.model === model)
 const selectedNative = nativeModel?.model===model ? nativeModel : undefined
 const selectedWllama = wasmModel?.model===model ? wasmModel : undefined
 const cpuModel = selectedNative ?? selectedWllama
 const cpuLabel = selectedWllama ? 'Wllama' : 'llama.cpp'
 const translationWebNN = selectedWebNN ?? webnnModels.find(m => m.model === automaticModel)
 const modelReady = cpuModel ? cpuModel.installed && (!selectedWllama || crossOriginIsolated) :
   !!selectedWebNN?.installed && hasWebNN
 const modelLabel = cpuModel ? `${cpuModel.name} · ${cpuLabel} (CPU)` :
   selectedWebNN ? selectedWebNN.name + ' · WebNN' : model
 const modelStatus = cpuModel ? (modelReady ? `${cpuLabel} CPU disponible` :
   cpuModel.installed ? 'Wllama indisponible dans cette page' : `${cpuLabel} à installer`) :
   modelReady ? 'WebNN disponible' : hasWebNN ? 'Modèle WebNN à installer' : 'WebNN indisponible'
 async function ask(text=question, prepareOnly=false) {
   if (!doc || !text.trim() || busy || !model) return
   if (!modelReady) {
     setError(selectedWllama ? (selectedWllama.installed ? 'Ouvrez Clair sur localhost pour activer Wllama.' :
       'Installez le GGUF avec python -m scripts.benchmark_cpu --install-gguf.') :
       selectedNative ? 'Installez le modèle CPU avec python -m scripts.benchmark_cpu --install-only.' :
       hasWebNN ? 'Lancez installer.bat pour installer le modèle WebNN.' : 'Ouvrez Clair avec demarrer.bat pour activer WebNN dans Edge.')
     return
   }
   setBusy(true)
   setDeviceReport(null)
   setError('')
   if (!prepareOnly) {
     setQuestion('')
     setMessages(old=>[...old,{question:text,answer:'',sources:[],metrics:{}}])
   }
   setStatus(prepareOnly ? 'Préparation des synthèses…' : 'Recherche dans le document…')
   const controller = new AbortController()
   abort.current = controller
   let complete = false
   const updateLast = (update: (message: Message) => Message) =>
     setMessages(old => [...old.slice(0,-1), update(old[old.length-1])])
   async function event(item: any) {
     if (item.type === 'error') throw Error(item.message)
     if (item.type === 'status') setStatus(item.text)
     if (item.type === 'generate') setDeviceReport(await generateInBrowser(item, controller.signal, setStatus, device))
     if (item.type === 'generate_wllama') await generateWithWllama(item, controller.signal, setStatus)
     if (item.type === 'token' && !prepareOnly) updateLast(m=>({...m,answer:m.answer+item.text}))
     if (item.type === 'done' || item.type === 'prepared') {
       complete = true
       if (!prepareOnly) updateLast(()=>({question:text,...item}))
       setStatus('')
     }
   }
   try {
     const r = await fetch(`/api/documents/${doc.id}/ask`,{
       ...post({question:text,model,strategy,output_format:format,prepare_only:prepareOnly,webnn_device:device}),
       signal:controller.signal,
     })
     if (!r.ok) throw Error((await r.json()).detail)
     const reader = r.body!.getReader()
     const decoder = new TextDecoder()
     try {
       let buffer = ''
       while (true) {
         const {value,done} = await reader.read()
         buffer += decoder.decode(value,{stream:!done})
         const lines = buffer.split('\n')
         buffer = lines.pop()!
         for (const line of lines) if (line.trim()) await event(JSON.parse(line))
         if (done) {
           if (buffer.trim()) await event(JSON.parse(buffer))
           break
         }
       }
     } finally { await reader.cancel() }
     if (!complete) throw Error('Flux interrompu avant la fin.')
     if (prepareOnly) setDoc(await api(`/documents/${doc.id}`))
   } catch (e) {
     setStatus('')
     if ((e as Error).name!=='AbortError') setError(String(e))
     if (!prepareOnly) updateLast(m=>({...m,warnings:['Réponse interrompue, non enregistrée.']}))
   } finally {
     if (selectedWebNN) scheduleBrowserModelRelease()
     if (selectedWllama) await releaseWllama()
     setBusy(false)
     abort.current = null
     refresh()
   }
 }
 function prepare(){ return ask('Préparer les synthèses',true) }
 async function remove(){if(!doc||!confirm('Supprimer ce document, ses analyses et son historique de cet ordinateur ?'))return;try{await api(`/documents/${doc.id}`,{method:'DELETE'});setDoc(null);setMessages([]);refresh()}catch(e){setError(String(e))}}
 function md(text:string){return <Markdown components={{img:()=>null,a:({children})=><span>{children}</span>}}>{text}</Markdown>}
 const last=messages.at(-1)
 return <div className="app" onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={e=>{if(!e.currentTarget.contains(e.relatedTarget as Node))setDrag(false)}} onDrop={e=>{e.preventDefault();setDrag(false);upload(e.dataTransfer.files[0])}}>
  <input hidden ref={input} type="file" accept=".pdf,.docx,.txt" onChange={e=>upload(e.target.files?.[0])}/>
  <aside className="sidebar"><a className="brand" href="/" aria-label="Clair accueil"><span className="brand-icon"><Layers size={22}/></span>clair<span className="brand-dot">.</span></a><div className="workspace-label">ESPACE DOCUMENTAIRE <LockKeyhole size={12}/></div>
   <button className="import" disabled={uploading||busy} onClick={()=>input.current?.click()}>{uploading?<LoaderCircle className="spin" size={16}/>:<Plus size={17}/>} {uploading?'Extraction en cours…':'Importer un document'}</button>
   <div className="side-heading">MES DOCUMENTS <span>{docs.length.toString().padStart(2,'0')}</span></div>
   <nav className="document-list">{docs.length===0?<div className="empty-docs">Votre bibliothèque est prête.<br/>Ajoutez votre premier document.</div>:docs.map(d=><button key={d.id} disabled={busy} onClick={()=>select(d.id)} className={'doc-item '+(doc?.id===d.id?'selected':'')}><FileText size={18}/><span><b>{d.name}</b><small>{d.kind.toUpperCase()} · {d.pages} {d.kind==='pdf'?'pages':'blocs'}</small></span>{doc?.id===d.id&&<span className="selected-dot"/>}</button>)}</nav>
   {doc&&<><div className="side-heading outline-label">SOMMAIRE <span>{doc.sections.length}</span></div><nav className="outline">{doc.sections.map((s,i)=><button key={s.id} onClick={()=>showPage(s.page,s.title)} title={s.title}><span>{String(i+1).padStart(2,'0')}</span>{s.title}<ChevronRight size={12}/></button>)}</nav><div className="doc-info"><div><Check size={14}/> Texte extrait <span>{Math.round(doc.extraction_ms)} ms</span></div><div><Layers size={14}/> {doc.summaries_cached} résumés en cache</div><button disabled={busy||!model} onClick={prepare}><BookOpen size={14}/> Préparer les synthèses</button><button className="delete" disabled={busy} onClick={remove}><Trash2 size={13}/> Supprimer le document</button></div></>}
   <div className="privacy"><ShieldCheck size={19}/><div><b>Vos fichiers restent ici.</b><small>Traitement local · Aucun compte</small></div></div>
  </aside>
  <main><header><div className="breadcrumb"><FolderOpen size={15}/> Bibliothèque <ChevronRight size={13}/><b>{doc?'Conversation':'Nouveau document'}</b></div><div className="runtime"><span className={'dot '+(modelReady?'green':'amber')}/><span>{modelStatus}</span>{deviceReport&&<span className="cpu">{deviceReport.device.toUpperCase()}</span>}<button className="icon-button" aria-label="Paramètres du modèle" onClick={()=>setSettings(!settings)}><SlidersHorizontal size={17}/></button></div></header>
   {settings&&<div className="settings"><label>Modèle local<select value={preferredModel} onChange={e=>{releaseBrowserModel();setModelPreference(e.target.value)}} disabled={busy}><option value="">Automatique{automaticModel?` · ${automaticModel}`:''}</option>{webnnModels.length>0&&<optgroup label="WebNN dans Edge">{webnnModels.map(m=><option key={m.model} value={m.model}>{m.name} · WebNN</option>)}</optgroup>}{wasmModel&&<optgroup label="WebAssembly dans Edge"><option value={wasmModel.model}>{wasmModel.name} · Wllama (CPU){wasmModel.installed?'':' — à installer'}</option></optgroup>}{nativeModel&&<optgroup label="CPU natif"><option value={nativeModel.model}>{nativeModel.name} · llama.cpp (CPU){nativeModel.installed?'':' — à installer'}</option></optgroup>}</select></label><label>Stratégie<select value={strategy} onChange={e=>setStrategy(e.target.value)}><option value="auto">Automatique</option><option value="direct">Lecture directe</option><option value="fast">Résumé rapide (sélection extractive)</option><option value="summary">Résumé approfondi (tous les blocs)</option><option value="hybrid">Résumé + BM25</option><option value="bm25">Recherche BM25</option></select></label>{(!cpuModel||mode==='translate')&&<><label>Calcul WebNN<select value={device} onChange={e=>{resetDeviceChecks();setDevice(e.target.value as DeviceSelection);setDeviceReport(null)}} disabled={busy}>{Object.entries(deviceLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><button className="device-retest" disabled={busy} onClick={()=>{resetDeviceChecks();setDeviceReport(null)}}>Retester GPU / NPU au prochain calcul</button><small>Utilisé pour les questions, les résumés et les traductions WebNN.{translationWebNN?` Contexte : ${translationWebNN.context} tokens.`:''}</small></>}{cpuModel&&mode==='chat'&&<small>CPU uniquement · {cpuModel.context} tokens.</small>}</div>}
   {error&&<div role="alert" className="error">{error.replace(/^Error: /,'')}<button onClick={()=>setError('')} aria-label="Fermer l’erreur"><X size={16}/></button></div>}
   {doc?.warnings.length? <details className="document-warnings"><summary>{doc.warnings.length} information(s) sur l’extraction</summary>{doc.warnings.map((w,i)=><p key={i}>{w}</p>)}</details>:null}
   <div className="content">
    {!doc?<div className="welcome"><div className="eyebrow"><span/> VOTRE LECTURE, ÉCLAIRÉE</div><h1>Faites parler<br/>vos documents.</h1><p>Un résumé, un chiffre, une décision.<br/>Retrouvez l’essentiel et remontez à la source.</p><button className="dropzone" onClick={()=>input.current?.click()} disabled={uploading}><span className="upload-icon">{uploading?<LoaderCircle className="spin"/>:<Upload size={24}/>}</span><b>{uploading?'Extraction locale en cours…':'Déposez votre document ici'}</b><span>ou cliquez pour parcourir vos fichiers</span><small>PDF, DOCX ou TXT · Jusqu’à {health?.max_upload_mb||100} Mo</small></button><div className="demo-line">Envie d’essayer ? <button onClick={demo} disabled={uploading}>Ouvrir le document de démonstration <ChevronRight size={13}/></button></div><div className="trust-row"><span><LockKeyhole size={14}/> 100 % local</span><span><Search size={14}/> Sources consultables</span><span><ShieldCheck size={14}/> Aucun cloud</span></div></div>:<>
    <div className="document-heading"><div className="eyebrow">DOCUMENT OUVERT <span className="ready"><Check size={11}/> PRÊT</span></div><h1>{doc.name.replace(/\.(pdf|docx|txt)$/i,'')}</h1><p>{doc.pages} {doc.kind==='pdf'?'pages':'blocs de texte'} <span>·</span> {doc.sections.length} sections détectées <span>·</span> {new Intl.NumberFormat('fr').format(doc.chars)} octets de texte</p></div>
    <nav className="document-modes" aria-label="Utilisation du document"><button aria-pressed={mode==='chat'} disabled={busy} onClick={()=>setMode('chat')}>Questions et résumés</button><button aria-pressed={mode==='translate'} disabled={busy} onClick={()=>setMode('translate')}>Traduire</button></nav>
    {(!cpuModel||mode==='translate')&&<DeviceStatus preference={device} report={deviceReport}/>}
    {mode==='translate'?<TranslationPanel key={doc.id} docId={doc.id} model={translationWebNN?.model||''} modelName={translationWebNN?.name||''} device={device} onDeviceReport={setDeviceReport} ready={!!translationWebNN?.installed&&hasWebNN} busy={busy} onBusyChange={setBusy}/>:<>
    {messages.length===0&&<div className="conversation-intro"><span className="assistant-icon"><MessageSquare size={22}/></span><h2>Qu’aimeriez-vous comprendre ?</h2><p>Posez une question ou commencez par une piste.<br/>Les réponses s’appuient sur votre document.</p><div className="prompt-grid">{quick.map(([title,q],i)=><button key={title} onClick={()=>ask(q)} disabled={!model||busy}><span>0{i+1}</span><b>{title}</b><ChevronRight size={16}/><small>{q}</small></button>)}</div></div>}
    <div className="messages">{messages.map((m,i)=><article className="exchange" key={i}><div className="question"><span>VOUS</span><p>{m.question}</p></div><div className="answer"><div className="answer-label"><span className="mini-brand"><Layers size={14}/></span> CLAIR {m.metrics.runtime==='webnn'&&<small>· WebNN {m.metrics.device?.toUpperCase()}</small>}{m.metrics.runtime==='llamacpp'&&<small>· llama.cpp CPU</small>}{m.metrics.runtime==='wllama'&&<small>· Wllama CPU</small>}{m.metrics.runtime==='ollama'&&<small>· {m.metrics.model}</small>}{m.metrics.cached_answer&&<small>· réponse réutilisée</small>}{busy&&i===messages.length-1&&<small>· réponse provisoire</small>}</div>{md(m.answer)}{m.sources.length>0&&<div className="sources"><small>PASSAGES SOURCES · CLIQUEZ POUR VÉRIFIER</small>{m.sources.map(s=><button key={s.id} onClick={()=>showSource(s.id)}><FileText size={13}/><b>S{s.id}</b> {s.page?`Page ${s.page}`:s.title}<ChevronRight size={12}/></button>)}</div>}{m.metrics.coverage&&<details className="answer-notes"><summary>{m.metrics.coverage.partial?'Sélection partielle':'Tous les blocs extraits parcourus'} : {m.metrics.coverage.sections_selected}/{m.metrics.coverage.sections_total} sections · {m.metrics.coverage.pages_selected.length} pages retenues</summary><p>Passages fournis au modèle ; certains faits peuvent être omis même dans une section retenue.</p>{m.metrics.coverage.chapters&&<p>{m.metrics.coverage.chapters.filter((c:any)=>c.selected_pages.length>0).length}/{m.metrics.coverage.chapters.length} chapitres avec un passage retenu.</p>}{m.metrics.coverage.sections.map((s:any)=><p key={s.id}>{s.selected?'Retenue':'Non retenue'} · {s.title} · page/bloc {s.page}</p>)}</details>}{m.warnings&&<details className="answer-notes"><summary>Portée et limites de la réponse</summary>{m.warnings.map((w,j)=><p key={j}>{w}</p>)}</details>}</div></article>)}{busy&&<div className="stream-status"><LoaderCircle className="spin" size={14}/>{status}</div>}<div ref={end}/></div>
    </>}
    </>}
   </div>
   {doc&&mode==='chat'&&<div className="composer-wrap">{messages.length>0&&<div className="quick-row">{quick.map(([title,q])=><button disabled={busy||!model} key={title} onClick={()=>ask(q)}>{title}</button>)}</div>}<form className="composer" onSubmit={e=>{e.preventDefault();ask()}}><textarea value={question} onChange={e=>setQuestion(e.target.value)} maxLength={1200} placeholder="Posez une question à votre document…" aria-label="Votre question" onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();ask()}}}/><div className="composer-toolbar"><div><span className={'dot '+(modelReady?'green':'amber')}/><span>{modelLabel||'Sélectionnez un modèle dans les paramètres'}</span><select aria-label="Format de réponse" value={format} onChange={e=>setFormat(e.target.value)}>{['réponse courte','réponse détaillée','résumé structuré','points clés'].map(v=><option key={v}>{v}</option>)}</select></div>{busy?<button type="button" className="send" aria-label="Arrêter la réponse" onClick={()=>abort.current?.abort()}><Square size={16}/></button>:<button className="send" aria-label="Envoyer la question" disabled={!question.trim()||!model}><ArrowUp size={20}/></button>}</div></form><div className="composer-note"><LockKeyhole size={11}/> Analyse locale. Vérifiez les réponses à l’aide des passages sources.</div></div>}
   <footer><span><span className="dot green"/> EXÉCUTION LOCALE</span><details><summary>Mesures techniques</summary><div className="metrics">{last?.metrics&&<pre>{JSON.stringify(last.metrics,null,2)}</pre>}<p>Le moteur et les durées de chaque appel figurent dans les mesures de la réponse.</p></div></details><span>CLAIR / V0.1</span></footer>
  </main>
  {source&&<div className="source-backdrop" onClick={()=>setSource(null)}><aside className="source-panel" onClick={e=>e.stopPropagation()}><div className="source-header"><div><div className="eyebrow">TEXTE ORIGINAL</div><h2>{source.physical_page?'Page':'Bloc'} {source.page}</h2></div><button className="icon-button" aria-label="Fermer la source" onClick={()=>setSource(null)}><X/></button></div><h3>{source.title}</h3><pre>{source.text}</pre>{source.tables.map((t,i)=><table key={i}><tbody>{t.map((r:any[],j:number)=><tr key={j}>{r.map((cell,k)=><td key={k}>{cell}</td>)}</tr>)}</tbody></table>)}{doc?.kind==='pdf'&&<a href={`/api/documents/${doc.id}/original#page=${source.page}`} target="_blank" rel="noreferrer">Ouvrir le PDF à cette page ↗</a>}</aside></div>}
  {drag&&<div className="drag-overlay"><Upload size={40}/><h2>Déposez votre document</h2><p>Il sera traité uniquement sur cet ordinateur.</p></div>}
 </div>
}
createRoot(document.getElementById('root')!).render(<App/>);
