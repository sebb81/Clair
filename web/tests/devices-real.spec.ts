import {test,expect} from '@playwright/test'

test.use({launchOptions:{args:['--enable-features=WebMachineLearningNeuralNetwork']}})

test('Question réelle avec priorité GPU et métriques du contexte exécuté',async({page,request},testInfo)=>{
  test.skip(process.env.CLAIR_REAL_DEVICE_TEST!=='1','Activer CLAIR_REAL_DEVICE_TEST=1 pour effectuer un calcul local réel.')
  test.setTimeout(240000)
  const model='qwen2.5-1.5b:webnn'
  await page.addInitScript(model=>{
    localStorage.setItem('clair-webnn-model',model)
    localStorage.setItem('clair-webnn-device','gpu')
  },model)
  const results:any[]=[],errors:string[]=[],external:string[]=[]
  page.on('pageerror',e=>errors.push(e.message))
  page.on('request',r=>{
    if(r.url().includes('/api/webnn/results/'))results.push(r.postDataJSON())
    if(new URL(r.url()).origin!=='http://127.0.0.1:8765')external.push(r.url())
  })
  let id=''
  try {
    await page.goto('/')
    const uploaded=page.waitForResponse(r=>r.url().endsWith('/api/documents')&&r.request().method()==='POST')
    await page.locator('input[type=file]').setInputFiles({name:'materiel-validation.txt',mimeType:'text/plain',buffer:Buffer.from('Le budget annoncé pour 2027 est de 240 000 euros. La date de lancement est septembre 2027.','utf8')})
    id=(await (await uploaded).json()).document.id
    await page.getByLabel('Format de réponse').selectOption('réponse courte')
    await page.getByLabel('Votre question').fill('Quel est le budget annoncé pour 2027 ?')
    await page.getByRole('button',{name:'Envoyer la question'}).click()
    await expect(page.locator('.exchange').last().locator('.answer')).toContainText(/240[\s,. ]*000/,{timeout:180000})
    await expect(page.getByRole('button',{name:'Envoyer la question'})).toBeVisible({timeout:180000})
    expect(results).toHaveLength(1)
    expect(results[0].device_preference).toBe('gpu')
    expect(results[0].dispatches).toBeGreaterThan(0)
    expect(results[0].device_attempts.at(-1).status).toBe('used')
    await page.getByText('Détail du matériel et des replis').click()
    await page.screenshot({path:testInfo.outputPath('question-device-report.png'),fullPage:true})
    await testInfo.attach('device-result',{body:JSON.stringify(results,null,2),contentType:'application/json'})
    expect(errors).toEqual([])
    expect(external).toEqual([])
  } finally {if(id)await request.delete(`/api/documents/${id}`)}
})
