import {test, expect} from '@playwright/test'

test('Résumé utilise WebNN après un ancien choix Ollama', async ({page}) => {
 const doc={id:'ui-fast',name:'Résumé test.pdf',kind:'pdf',pages:111,chars:180000,chunks:299,warnings:[],extraction_ms:8,summaries_cached:0,sections:[{id:1,title:'Chapitre 1',page:9},{id:2,title:'Chapitre 2',page:37}]}
 await page.addInitScript(() => localStorage.setItem('clair-generation-model','qwen3.5:9b'))
 await page.route('**/api/**', async route => {
  const url=new URL(route.request().url())
  let body:any={}
  if(url.pathname==='/api/health') body={recommended_model:'qwen2.5-1.5b:webnn',webnn_models:[{name:'Qwen2.5',model:'qwen2.5-1.5b:webnn',context:2048,installed:true}]}
  else if(url.pathname==='/api/documents') body=[doc]
  else if(url.pathname.endsWith('/messages')) body=[]
  else if(url.pathname.endsWith('/preparation')) body={status:'idle'}
  else if(url.pathname.endsWith('/ask')) {
   expect(route.request().postDataJSON()).toMatchObject({model:'qwen2.5-1.5b:webnn',strategy:'auto'})
   const event={type:'done',answer:'Une conclusion sourcée [S10].',sources:[{id:10,page:9,title:'Chapitre 1',text:'Texte original',section:1}],warnings:['Sélection partielle.'],metrics:{model_calls:1,coverage:{partial:true,sections_selected:1,sections_total:2,pages_selected:[9],sections:[{id:1,title:'Chapitre 1',page:9,selected:true},{id:2,title:'Chapitre 2',page:37,selected:false}]}}}
   return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify(event)+'\n'})
  } else body=doc
  await route.fulfill({json:body})
 })
 await page.goto('/')
 await page.evaluate(() => Object.defineProperty(navigator,'ml',{value:{},configurable:true}))
 await page.locator('.doc-item').click()
 await page.locator('.prompt-grid').getByRole('button',{name:/Résumé.*Fais-moi/}).click()
 await expect(page.locator('.answer')).toContainText('Une conclusion sourcée')
 await page.getByText('Sélection partielle : 1/2 sections').click()
 await expect(page.locator('.answer')).toContainText('Non retenue · Chapitre 2')
 await expect(page.locator('.sources')).toContainText('Page 9')
})
