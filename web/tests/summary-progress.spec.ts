import {test, expect} from '@playwright/test'

test.use({launchOptions: {args: ['--enable-features=WebMachineLearningNeuralNetwork']}})

test('PDF réel : progression du résumé, arrêt et cache conservé', async ({page, request}, testInfo) => {
 const {webnn} = await (await request.get('/api/health')).json()
 test.skip(!webnn?.installed, 'Le modèle WebNN est installé par installer.bat.')
 await page.addInitScript(model => localStorage.setItem('clair-webnn-model', model), webnn.model)
 const documents = await (await request.get('/api/documents')).json()
 const doc = documents.find((item:any) => item.pages === 111)
 test.skip(!doc, 'Le PDF utilisateur de 111 pages doit être présent localement.')
 const before = await (await request.get(`/api/documents/${doc.id}`)).json()
 await page.goto('/')
 await page.locator('.doc-item').filter({hasText:doc.name}).click()
 await page.getByRole('button', {name:'Paramètres du modèle'}).click()
 await page.getByLabel('Stratégie').selectOption('summary')
 await page.getByLabel('Votre question').fill('Fais-moi un résumé structuré de ce document.')
 await page.getByRole('button', {name:'Envoyer la question'}).click()
 // With a complete cache the hierarchy can finish before the first UI paint.
 await expect(page.locator('.stream-status')).toContainText(/Préparation|Vérification|Chargement|Compilation/, {timeout:15000})
 await page.screenshot({path:testInfo.outputPath('summary-progress.png'), fullPage:true})
 await page.getByRole('button', {name:'Arrêter la réponse'}).click()
 await expect(page.getByRole('button', {name:'Envoyer la question'})).toBeVisible()
 await expect.poll(async () => (await (await request.get('/api/health')).json()).busy, {timeout:10000}).toBe(false)
 const after = await (await request.get(`/api/documents/${doc.id}`)).json()
 expect(after.summaries_cached).toBeGreaterThanOrEqual(before.summaries_cached)
})
