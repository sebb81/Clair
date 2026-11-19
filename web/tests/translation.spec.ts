import {test,expect} from '@playwright/test'

test('Traduction : langue, progression, export et reprise après rechargement',async({page},testInfo)=>{
  const doc={id:'translation-ui',name:'Document test.pdf',kind:'pdf',pages:2,chars:500,chunks:2,warnings:[],extraction_ms:5,summaries_cached:0,sections:[]}
  const model='qwen3-4b:webnn'
  let jobs:any[]=[]
  await page.addInitScript(()=>Object.defineProperty(navigator,'ml',{value:{},configurable:true}))
  await page.route('**/api/**',async route=>{
    const url=new URL(route.request().url())
    if(url.pathname==='/api/health') return route.fulfill({json:{recommended_model:model,webnn_models:[{model,name:'Qwen3 4B',context:3072,installed:true}]}})
    if(url.pathname==='/api/documents') return route.fulfill({json:[doc]})
    if(url.pathname.endsWith('/messages')) return route.fulfill({json:[]})
    if(url.pathname.endsWith('/translations')) return route.fulfill({json:{languages:{en:'Anglais',fr:'Français',de:'Allemand'},translations:jobs}})
    if(url.pathname.endsWith('/translate')) {
      expect(route.request().postDataJSON()).toEqual({model,language:'de',webnn_device:'npu'})
      const partial={id:'job-ui',model,language:'de',language_name:'Allemand',completed:1,total:2,status:'running',warnings:['Traduction à relire.'],error:''}
      jobs=[{...partial,completed:2,status:'complete'}]
      return route.fulfill({contentType:'application/x-ndjson',body:[{type:'translation_progress',translation:partial},{type:'translation_done',translation:jobs[0]}].map(x=>JSON.stringify(x)).join('\n')+'\n'})
    }
    return route.fulfill({json:doc})
  })
  await page.goto('/')
  await page.locator('.doc-item').click()
  await page.getByRole('button',{name:'Paramètres du modèle'}).click()
  await page.getByLabel('Calcul WebNN').selectOption('npu')
  await page.getByRole('button',{name:'Traduire',exact:true}).click()
  await page.getByLabel('Langue de traduction').selectOption('de')
  await page.getByRole('button',{name:'Traduire le document',exact:true}).click()
  await expect(page.getByText('2 / 2 blocs traduits')).toBeVisible()
  const link=page.getByRole('link',{name:'Télécharger la traduction en DOCX'})
  await expect(link).toHaveAttribute('href','/api/documents/translation-ui/translations/job-ui/download')
  await page.screenshot({path:testInfo.outputPath('translation-desktop.png'),fullPage:true})
  await page.setViewportSize({width:390,height:844})
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true)
  await page.screenshot({path:testInfo.outputPath('translation-mobile.png'),fullPage:true})
  await page.reload()
  await page.locator('.doc-item').click()
  await page.getByRole('button',{name:'Traduire',exact:true}).click()
  await page.getByLabel('Langue de traduction').selectOption('de')
  await expect(page.getByRole('link',{name:'Télécharger la traduction en DOCX'})).toBeVisible()
})

test('Une erreur conserve la reprise et ne propose aucun export complet',async({page})=>{
  const model='qwen3-4b:webnn'
  const doc={id:'translation-error',name:'Test.txt',kind:'txt',pages:1,chars:500,chunks:2,warnings:[],extraction_ms:0,summaries_cached:0,sections:[]}
  const job={id:'partial',model,language:'en',language_name:'Anglais',completed:1,total:2,status:'error',warnings:[],error:'Calcul interrompu.'}
  await page.addInitScript(()=>Object.defineProperty(navigator,'ml',{value:{},configurable:true}))
  await page.route('**/api/**',route=>{
    const pathname=new URL(route.request().url()).pathname
    if(pathname==='/api/health') return route.fulfill({json:{recommended_model:model,webnn_models:[{model,name:'Qwen3 4B',context:3072,installed:true}]}})
    if(pathname==='/api/documents') return route.fulfill({json:[doc]})
    if(pathname.endsWith('/messages')) return route.fulfill({json:[]})
    if(pathname.endsWith('/translations')) return route.fulfill({json:{languages:{en:'Anglais'},translations:[job]}})
    if(pathname.endsWith('/translate')) return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'error',message:'Calcul interrompu.'})+'\n'})
    return route.fulfill({json:doc})
  })
  await page.goto('/')
  await page.locator('.doc-item').click()
  await page.getByRole('button',{name:'Traduire',exact:true}).click()
  await page.getByRole('button',{name:'Reprendre la traduction'}).click()
  await expect(page.getByRole('alert')).toContainText('Calcul interrompu.')
  await expect(page.getByRole('link',{name:'Télécharger la traduction en DOCX'})).toHaveCount(0)
  await expect(page.getByRole('button',{name:'Reprendre la traduction'})).toBeEnabled()
})
