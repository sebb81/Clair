import {test,expect,type Page} from '@playwright/test'

const model='qwen3-4b:webnn'
const profile={id:'qwen3-4b',name:'Qwen3',layers:36,heads:8,headSize:128,vocabSize:151936,eos:[151645],chat:'qwen3'}
async function setup(page:Page,outcomes:Record<string,string>,preference='auto') {
  await page.addInitScript(({outcomes,preference})=>{
    Object.defineProperty(navigator,'ml',{value:{},configurable:true})
    localStorage.setItem('clair-webnn-device',preference)
    ;(window as any).deviceCalls=[]
    ;(window as any).postedResults=[]
    ;(window as any).workerStarts=0
    ;(window as any).workerReleases=0
    ;(window as any).workerStops=0
    class SimulatedWorker {
      onmessage:any=null;onerror:any=null;stopped=false
      constructor(){(window as any).workerStarts++}
      terminate(){this.stopped=true;(window as any).workerStops++}
      postMessage(data:any){
        if(data.type==='release'){
          ;(window as any).workerReleases++
          setTimeout(()=>this.onmessage?.({data:{type:'released'}}),1)
          return
        }
        ;(window as any).deviceCalls.push(data.device)
        const error=outcomes[data.device]
        setTimeout(()=>{
          if(this.stopped)return
          if(error==='hang')return
          this.onmessage?.({data:error?{type:'error',message:error}:{type:'result',result:{device:data.device,dispatches:8,text:'Budget 240 000 euros [S1].',done_reason:'stop',prompt_tokens:20,output_tokens:12}}})
        },1)
      }
    }
    Object.defineProperty(window,'Worker',{value:SimulatedWorker})
  },{outcomes,preference})
  const doc={id:'device-test',name:'Matériel.pdf',kind:'pdf',pages:1,chars:100,chunks:1,warnings:[],extraction_ms:1,summaries_cached:0,sections:[]}
  let generation=0
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url())
    if(url.pathname==='/api/health')return route.fulfill({json:{recommended_model:model,webnn_models:[{model,name:'Qwen3',context:3072,installed:true}]}})
    if(url.pathname==='/api/documents')return route.fulfill({json:[doc]})
    if(url.pathname.endsWith('/messages'))return route.fulfill({json:[]})
    if(url.pathname.includes('/webnn/results/')) {
      await page.evaluate(value=>(window as any).postedResults.push(value),route.request().postDataJSON())
      return route.fulfill({json:{accepted:true}})
    }
    if(url.pathname.endsWith('/ask')) {
      const done={type:'done',answer:'Budget 240 000 euros [S1].',sources:[],metrics:{runtime:'webnn',model}}
      const request={type:'generate',id:'fake-'+(++generation),messages:[{role:'user',content:'Budget ?'}],context:3072,max_tokens:128,json_output:false,model:profile}
      return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify(request)+'\n'+JSON.stringify(done)+'\n'})
    }
    return route.fulfill({json:doc})
  })
  await page.goto('/')
  await page.locator('.doc-item').click()
}
async function ask(page:Page,text='Quel est le budget ?') {
  await page.getByLabel('Votre question').fill(text)
  await page.getByRole('button',{name:'Envoyer la question'}).click()
  await expect(page.getByRole('button',{name:'Envoyer la question'})).toBeVisible()
}

test('Automatique : NPU indisponible puis GPU validé et diagnostic conservé',async({page})=>{
  await setup(page,{npu:'NPU non disponible'})
  await ask(page)
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu','gpu'])
  await expect(page.locator('.device-status')).toContainText('GPU · génération validée')
  await page.getByText('Détail du matériel et des replis').click()
  await expect(page.locator('.device-status')).toContainText('NPU non disponible')
  const [result]=await page.evaluate(()=>(window as any).postedResults)
  expect(result).toMatchObject({device:'gpu',device_preference:'auto',hardware_identity_verified:false})
  expect(result.device_attempts.map((a:any)=>a.status)).toEqual(['failed','used'])
})

test('GPU prioritaire : repli sur NPU puis CPU si les deux accélérateurs échouent',async({page})=>{
  await setup(page,{gpu:'Compilation GPU impossible',npu:'Compilation NPU impossible'},'gpu')
  await ask(page)
  await ask(page,'Quel est le budget pour 2027 ?')
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['gpu','npu','cpu','cpu'])
  const results=await page.evaluate(()=>(window as any).postedResults)
  expect(results[1].device_attempts.map((a:any)=>a.status)).toEqual(['skipped','skipped','used'])
  await page.getByRole('button',{name:'Paramètres du modèle'}).click()
  await page.getByRole('button',{name:'Retester GPU / NPU au prochain calcul'}).click()
  await ask(page,'Et le budget total ?')
  expect((await page.evaluate(()=>(window as any).deviceCalls)).slice(-3)).toEqual(['gpu','npu','cpu'])
})

test('Préférence NPU persistante et CPU uniquement sans essai accélérateur',async({page})=>{
  await setup(page,{},'npu')
  await ask(page)
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu'])
  await page.getByRole('button',{name:'Paramètres du modèle'}).click()
  await expect(page.getByLabel('Calcul WebNN')).toHaveValue('npu')
  await page.getByLabel('Calcul WebNN').selectOption('cpu')
  await ask(page,'Quel montant ?')
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu','cpu'])
  expect(await page.evaluate(()=>localStorage.getItem('clair-webnn-device'))).toBe('cpu')
})

test('L’arrêt pendant un essai accélérateur ne déclenche aucun repli',async({page})=>{
  await setup(page,{npu:'hang'})
  await page.getByLabel('Votre question').fill('Budget ?')
  await page.getByRole('button',{name:'Envoyer la question'}).click()
  await expect.poll(()=>page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu'])
  await page.getByRole('button',{name:'Arrêter la réponse'}).click()
  await expect(page.getByRole('button',{name:'Envoyer la question'})).toBeVisible()
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu'])
})

test('Échec de tous les périphériques : erreur envoyée au serveur et affichée',async({page})=>{
  await setup(page,{npu:'NPU absent',gpu:'GPU absent',cpu:'CPU en erreur'})
  await ask(page)
  await expect(page.getByRole('alert')).toContainText('CPU en erreur')
  const [result]=await page.evaluate(()=>(window as any).postedResults)
  expect(result.error).toBe('CPU en erreur')
  expect(result.device_attempts).toHaveLength(3)
})

test('Un accélérateur bloqué expire puis le GPU est essayé',async({page})=>{
  await page.clock.install()
  await setup(page,{npu:'hang'})
  await page.getByLabel('Votre question').fill('Budget ?')
  await page.getByRole('button',{name:'Envoyer la question'}).click()
  await expect.poll(()=>page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu'])
  await page.clock.runFor(120010)
  await expect(page.getByRole('button',{name:'Envoyer la question'})).toBeVisible()
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['npu','gpu'])
  const [result]=await page.evaluate(()=>(window as any).postedResults)
  expect(result.device_attempts[0].error).toContain('délai')
})

test('Le modèle est réutilisé puis libéré après 30 secondes sans demande',async({page})=>{
  await page.clock.install()
  await setup(page,{},'cpu')
  await ask(page)
  await ask(page,'Et en 2027 ?')
  expect(await page.evaluate(()=>(window as any).workerStarts)).toBe(1)
  expect(await page.evaluate(()=>(window as any).workerReleases)).toBe(0)
  await page.clock.runFor(30010)
  expect(await page.evaluate(()=>(window as any).workerReleases)).toBe(1)
  expect(await page.evaluate(()=>(window as any).workerStops)).toBe(1)
  await ask(page,'Quel est le montant ?')
  expect(await page.evaluate(()=>(window as any).workerStarts)).toBe(2)
})

test('La traduction réutilise le moteur entre les blocs puis libère ses sessions',async({page})=>{
  await setup(page,{},'cpu')
  const job={id:'memory-job',model,language:'en',language_name:'Anglais',completed:2,total:2,status:'complete',warnings:[],error:''}
  let complete=false
  await page.route('**/translations',route=>route.fulfill({json:{languages:{en:'Anglais'},translations:complete?[job]:[]}}))
  await page.route('**/translate',route=>{
    complete=true
    const generate=(id:string)=>({type:'generate',id,messages:[{role:'user',content:'Traduis ce texte.'}],context:1024,max_tokens:512,json_output:false,model:profile})
    return route.fulfill({contentType:'application/x-ndjson',body:[generate('block-1'),generate('block-2'),{type:'translation_done',translation:job}].map(x=>JSON.stringify(x)).join('\n')+'\n'})
  })
  await page.getByRole('button',{name:'Traduire',exact:true}).click()
  await page.getByRole('button',{name:'Traduire le document',exact:true}).click()
  await expect(page.getByRole('button',{name:'Traduction terminée',exact:true})).toBeVisible()
  expect(await page.evaluate(()=>(window as any).deviceCalls)).toEqual(['cpu','cpu'])
  expect(await page.evaluate(()=>(window as any).workerStarts)).toBe(1)
  expect(await page.evaluate(()=>(window as any).workerReleases)).toBe(1)
  expect(await page.evaluate(()=>(window as any).workerStops)).toBe(1)
})
