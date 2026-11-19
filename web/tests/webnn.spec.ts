import {expect, test} from '@playwright/test'
import path from 'node:path'

test.use({launchOptions: {chromiumSandbox: true, args: ['--enable-features=WebMachineLearningNeuralNetwork']}})

test('Compare Qwen2.5 WebNN dans le menu de Clair', async ({page, request}) => {
  const {webnn_models} = await (await request.get('/api/health')).json()
  const model = 'qwen2.5-1.5b:webnn'
  test.skip(!webnn_models?.some(candidate => candidate.model === model && candidate.installed),
    'Qwen2.5 est un modèle WebNN supplémentaire.')
  const docs = await (await request.get('/api/documents')).json()
  const doc = docs.find(item => item.kind === 'pdf' && item.name === 'horizon.pdf')
  test.skip(!doc, 'Le PDF Horizon doit être importé.')

  await page.goto('/')
  await page.locator('.doc-item').filter({hasText:'horizon.pdf'}).click()
  await page.getByRole('button', {name:'Paramètres du modèle'}).click()
  await page.getByLabel('Modèle local').selectOption(model)
  await page.getByLabel('Calcul WebNN').selectOption('auto')
  await page.getByLabel('Format de réponse').selectOption('réponse courte')
  await page.getByLabel('Votre question').fill('Quel est le budget annoncé pour 2027 ?')
  await page.getByRole('button', {name:'Envoyer la question'}).click()
  const answer = page.locator('.exchange').last().locator('.answer')
  await expect(answer).toContainText('WebNN', {timeout:90000})
  await expect(answer).toContainText(/240[\s ]000/)
  await expect(answer.locator('.sources button').filter({hasText:'Page 2'})).toBeVisible()
  const messages = await (await request.get(`/api/documents/${doc.id}/messages`)).json()
  const reply = messages.at(-1)
  expect(reply.metrics.model).toBe(model)
  expect(reply.metrics.runtime).toBe('webnn')
  expect(['cpu','gpu']).toContain(reply.metrics.device)
})

test('Edge résume un PDF avec WebNN et ouvre une source locale', async ({page, request}) => {
  test.setTimeout(300000)
  const {webnn} = await (await request.get('/api/health')).json()
  test.skip(!webnn?.installed, 'Le modèle WebNN est installé par installer.bat.')
  await page.addInitScript(model => localStorage.setItem('clair-webnn-model', model), webnn.model)
  const external: string[] = []
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin === 'http://127.0.0.1:8765') return route.continue()
    external.push(url.origin)
    return route.abort()
  })

  await page.goto('/')
  await expect(page.getByText('WebNN disponible')).toBeVisible()
  const upload = page.waitForResponse(response =>
    response.url().endsWith('/api/documents') && response.request().method() === 'POST')
  await page.locator('input[type=file]').setInputFiles(path.resolve('../tests/fixtures/horizon.pdf'))
  const {document} = await (await upload).json()
  await expect(page.getByRole('heading', {name: 'horizon', exact: true})).toBeVisible()
  const question = 'Fais-moi un résumé structuré de ce document.'
  await page.getByLabel('Votre question').fill(question)
  await page.getByRole('button', {name: 'Envoyer la question'}).click()
  const answer = page.locator('.exchange').last().locator('.answer')
  await expect(answer.locator('.sources button').first()).toBeVisible({timeout: 240000})
  await expect(answer).toContainText('WebNN')
  await answer.locator('.sources button').first().click()
  await expect(page.locator('.source-panel').getByRole('heading', {name: /Page \d+/})).toBeVisible()

  const messages = await (await request.get(`/api/documents/${document.id}/messages`)).json()
  const reply = messages.at(-1)
  expect(reply.question).toBe(question)
  expect(reply.metrics.runtime).toBe('webnn')
  expect(['cpu', 'gpu']).toContain(reply.metrics.device)
  if (!reply.metrics.cached_answer) expect(reply.metrics.calls.at(-1).dispatches).toBeGreaterThan(0)
  expect(external).toEqual([])
})
