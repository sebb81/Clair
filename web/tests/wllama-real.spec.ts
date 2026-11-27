import {execFile} from 'node:child_process'
import {mkdtemp,realpath,rm,writeFile} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {basename,dirname,join} from 'node:path'
import {promisify} from 'node:util'
import {chromium,test,expect} from '@playwright/test'

const exec=promisify(execFile)

function sampleMemory(profile:string, native:boolean) {
  let active=true
  let peakMiB=0
  const sampling=(async()=>{
    while (active) {
      const script=native ?
        "(Get-Process -Name llama-server -ErrorAction SilentlyContinue | Where-Object Path -Like '*cpu-bench*llama-server.exe' | Measure-Object -Property WorkingSet64 -Sum).Sum" :
        `$edges=Get-CimInstance Win32_Process -Filter "Name='msedge.exe'"
        $parent=$edges | Where-Object { $_.CommandLine -like '*${profile}*' -and $_.CommandLine -notlike '*--type=*' } | Select-Object -First 1
        if($parent) {
          $ids=$edges | Where-Object { $_.ProcessId -eq $parent.ProcessId -or $_.ParentProcessId -eq $parent.ProcessId } | ForEach-Object ProcessId
          (Get-Process -Id $ids -ErrorAction SilentlyContinue | Measure-Object -Property WorkingSet64 -Sum).Sum
        }`
      const {stdout}=await exec('powershell.exe',['-NoProfile','-Command',script],{windowsHide:true})
      peakMiB=Math.max(peakMiB,(Number(stdout.trim())||0)/1048576)
      if (active) await new Promise(resolve=>setTimeout(resolve,1000))
    }
  })().catch(()=>{})
  return async()=>{active=false;await sampling;return Math.round(peakMiB)}
}

test('Wllama dans Clair, citations, comparaison locale et arrêt',async({request},testInfo)=>{
  test.skip(process.env.CLAIR_REAL_WLLAMA_TEST!=='1','Activer sur une bibliothèque de validation avec le GGUF installé.')
  const withGPU=process.env.CLAIR_REAL_WLLAMA_WEBGPU==='1'
  test.setTimeout(withGPU ? 330000 : 240000)
  const temp=await realpath(tmpdir())
  const profile=await mkdtemp(join(temp,'clair-wllama-test-'))
  const args=process.env.CLAIR_REAL_WLLAMA_HIGH_PERFORMANCE==='1' ? ['--force-high-performance-gpu'] : []
  const context=await chromium.launchPersistentContext(profile,{channel:'msedge',viewport:{width:1440,height:1050},args})
  const page=context.pages()[0]??await context.newPage()
  const unexpected:string[]=[]
  page.on('pageerror',error=>console.error(error.message))
  page.on('console',message=>{if(message.type()==='error')console.error(message.text())})
  await page.addInitScript(()=>Object.defineProperty(navigator,'ml',{value:undefined,configurable:true}))
  await page.route('**/*',route=>{
    const url=new URL(route.request().url())
    if(url.origin===new URL(testInfo.project.use.baseURL!).origin&&!url.pathname.startsWith('/api/webnn/'))return route.continue()
    unexpected.push(url.href)
    return route.abort()
  })
  const {document}=await (await request.post('/api/demo')).json()
  const endpoint=`/api/documents/${document.id}`
  const getHistory=async()=>await (await request.get(endpoint+'/messages')).json()
  const report:Record<string,unknown>[]=[]

  try {
    await page.goto('/')
    expect(await page.evaluate(()=>crossOriginIsolated)).toBe(true)
    await page.locator('.doc-item').filter({hasText:'Projet Horizon'}).click()
    await page.getByRole('button',{name:'Paramètres du modèle'}).click()
    const models=page.getByLabel('Modèle local')
    await expect(models.locator('option[value="qwen3-4b:wllama"]')).toHaveText('Qwen3 4B · Wllama (CPU)')
    await page.getByLabel('Format de réponse').selectOption('réponse courte')
    const question=page.getByRole('textbox',{name:'Votre question'})

    if (withGPU) {
      await expect(models.locator('option[value="qwen3-4b:wllama-webgpu"]')).toHaveText('Qwen3 4B · Wllama (WebGPU)')
      const adapter=await page.evaluate(async()=>{
        const gpu=(navigator as Navigator&{gpu?:{requestAdapter():Promise<{info:{vendor:string;architecture:string;description:string}}|null>}}).gpu
        const info=(await gpu?.requestAdapter())?.info
        return info ? {vendor:info.vendor,architecture:info.architecture,description:info.description} : null
      })
      expect(adapter).not.toBeNull()
      await writeFile(testInfo.outputPath('edge-webgpu-adapter.json'),JSON.stringify(adapter,null,2)+'\n')
      // Use one cache for the CPU and WebGPU measurements, primed outside the comparison.
      await models.selectOption('qwen3-4b:wllama')
      await question.fill('Quel est le nom du projet ?')
      await page.getByRole('button',{name:'Envoyer la question'}).click()
      const warmup=page.locator('.exchange').last().getByText('· Wllama CPU')
      const error=page.getByRole('alert')
      await expect(warmup.or(error)).toBeVisible({timeout:120000})
      if (await error.isVisible()) throw Error(await error.innerText())
      await expect(page.getByRole('button',{name:'Arrêter la réponse'})).toHaveCount(0)
    }

    const engines=withGPU ? ['wllama-webgpu','wllama','llamacpp'] : ['wllama','llamacpp']
    for (const engine of engines) {
      await models.selectOption('qwen3-4b:'+engine)
      const gpu=engine==='wllama-webgpu'
      const tag=gpu ? 'Wllama WebGPU' : engine==='wllama' ? 'Wllama CPU' : 'llama.cpp CPU'
      for (const task of ['question','résumé']) {
        const length=(await getHistory()).length
        const stopSampling=sampleMemory(basename(profile),engine==='llamacpp')
        let peakMiB=0
        try {
          if (task==='question') {
            await question.fill('Quel est le budget annoncé pour 2027 ?')
            await page.getByRole('button',{name:'Envoyer la question'}).click()
          } else {
            await page.getByRole('button',{name:'Résumé',exact:true}).click()
          }
          const answer=page.locator('.exchange').last()
          const error=page.getByRole('alert')
          await expect(answer.getByText('· '+tag).or(error)).toBeVisible({timeout:120000})
          if (await error.isVisible()) throw Error(await error.innerText())
          await expect(answer.locator('.sources button').first()).toBeVisible()
          if (task==='question') await expect(answer).toContainText(/240[ \u00a0\u202f]?000/)
          await expect(page.getByRole('button',{name:'Arrêter la réponse'})).toHaveCount(0)
          if (engine!=='llamacpp'&&task==='question') {
            if (gpu) await expect(answer.getByText(/\d+\/\d+ couches GPU/)).toBeVisible()
            await page.screenshot({path:testInfo.outputPath(gpu?'clair-wllama-webgpu.png':'clair-wllama-cpu.png')})
            await answer.locator('.sources button').first().click()
            await expect(page.locator('.source-panel')).toContainText(/240[ \u00a0\u202f]?000/)
            await page.getByRole('button',{name:'Fermer la source'}).click()
          }
        } finally {
          peakMiB=await stopSampling()
        }
        const history=await getHistory()
        expect(history).toHaveLength(length+1)
        const answer=history.at(-1)
        expect(answer.metrics).toMatchObject({runtime:gpu?'wllama':engine,device:gpu?'gpu':'cpu',model:'qwen3-4b:'+engine})
        if (gpu) {
          expect(answer.metrics.gpu_layers).toBeGreaterThan(0)
          expect(answer.metrics.gpu_layers).toBeLessThanOrEqual(answer.metrics.total_layers)
        }
        expect(answer.answer).toMatch(/\[S\d+\]/)
        expect(answer.metrics.model_calls).toBeGreaterThan(0)
        if (task==='résumé') expect(answer.metrics.strategy).toBe('fast')
        if (engine==='wllama') expect(answer.metrics.threads).toBeGreaterThan(1)
        report.push({task,engine,peak_resident_mib:peakMiB,answer:answer.answer,metrics:answer.metrics})
      }
    }

    const finished=(await getHistory()).length
    await models.selectOption(withGPU?'qwen3-4b:wllama-webgpu':'qwen3-4b:wllama')
    await question.fill('Comment le budget de 2027 se répartit-il entre chaque poste ?')
    await page.getByRole('button',{name:'Envoyer la question'}).click()
    const generating=withGPU ? /Wllama rédige avec WebGPU/ : 'Wllama lit les passages et rédige sur CPU…'
    await expect(page.getByText(generating)).toBeVisible({timeout:45000})
    await page.getByRole('button',{name:'Arrêter la réponse'}).click()
    await expect.poll(async()=>(await (await request.get('/api/health')).json()).busy).toBe(false)
    await expect(models).toBeEnabled()
    expect(await getHistory()).toHaveLength(finished)
    expect(unexpected).toEqual([])
    await writeFile(testInfo.outputPath('comparison.json'),JSON.stringify(report,null,2)+'\n')
  } finally {
    await request.delete(endpoint)
    await context.close()
    const resolved=await realpath(profile)
    if (dirname(resolved)===temp&&basename(resolved).startsWith('clair-wllama-test-')) {
      await rm(resolved,{recursive:true,force:true})
    }
  }
})
