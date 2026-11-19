import {test,expect} from '@playwright/test'
import path from 'node:path'

test.use({launchOptions:{args:['--enable-features=WebMachineLearningNeuralNetwork']}})

test('Vraie traduction locale français anglais et téléchargement DOCX',async({page,request},testInfo)=>{
  test.skip(process.env.CLAIR_REAL_TRANSLATION_TEST!=='1','Activer explicitement CLAIR_REAL_TRANSLATION_TEST=1 pour calculer avec le modèle installé.')
  test.setTimeout(300000)
  const model='qwen3-4b:webnn'
  const preference=process.env.CLAIR_REAL_DEVICE||'cpu'
  const external:string[]=[],errors:string[]=[]
  const results:any[]=[]
  const input='Le budget est de 240 000 euros. Le lancement est prévu en septembre 2027.\n\nLe prestataire n’est pas encore choisi. Aucune décision définitive n’a été prise.'
  await page.addInitScript(id=>localStorage.setItem('clair-webnn-model',id),model)
  await page.addInitScript(device=>localStorage.setItem('clair-webnn-device',device),preference)
  page.on('pageerror',e=>errors.push(e.message))
  page.on('request',request=>{if(request.url().includes('/api/webnn/results/'))results.push(request.postDataJSON())})
  await page.route('**/*',route=>{
    const url=new URL(route.request().url())
    if(url.origin==='http://127.0.0.1:8765')return route.continue()
    external.push(url.href)
    return route.abort()
  })
  let docId=''
  try {
    await page.goto('/')
    const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/documents')&&r.request().method()==='POST')
    await page.locator('input[type=file]').setInputFiles({name:'traduction-validation.txt',mimeType:'text/plain',buffer:Buffer.from(input,'utf8')})
    docId=(await (await uploaded).json()).document.id
    await page.getByRole('button',{name:'Traduire',exact:true}).click()
    await page.getByLabel('Langue de traduction').selectOption('en')
    await page.getByRole('button',{name:'Traduire le document',exact:true}).click()
    const link=page.getByRole('link',{name:'Télécharger la traduction en DOCX'})
    await expect(link).toBeVisible({timeout:240000})
    const downloadEvent=page.waitForEvent('download')
    await link.click()
    const download=await downloadEvent
    await download.saveAs(path.resolve('../data/translation-validation/translation-en.docx'))
    await page.screenshot({path:testInfo.outputPath('translation-real.png'),fullPage:true})
    const jobs=await (await request.get(`/api/documents/${docId}/translations`)).json()
    expect(jobs.translations[0].completed).toBe(jobs.translations[0].total)
    expect(jobs.translations[0].status).toBe('complete')
    expect(jobs.translations[0].devices.length).toBeGreaterThan(0)
    expect(results.every(result=>result.device_preference===preference)).toBe(true)
    expect(results.every(result=>result.dispatches>0)).toBe(true)
    await page.getByText('Détail du matériel et des replis').click()
    await page.screenshot({path:testInfo.outputPath('translation-device-report.png'),fullPage:true})
    await testInfo.attach('device-results',{body:JSON.stringify(results,null,2),contentType:'application/json'})
    expect(external).toEqual([])
    expect(errors).toEqual([])
  } finally {
    if(docId) await request.delete(`/api/documents/${docId}`)
  }
})
