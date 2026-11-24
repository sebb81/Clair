import {test, expect} from '@playwright/test'

test('Clair sélectionne llama.cpp CPU et conserve les sources des réponses', async ({page, request}, testInfo) => {
  test.skip(process.env.CLAIR_REAL_LLAMACPP_TEST !== '1', 'Activer CLAIR_REAL_LLAMACPP_TEST=1 avec les poids GGUF installés.')
  test.setTimeout(90000)
  const unexpected: string[] = []
  await page.addInitScript(() => Object.defineProperty(navigator, 'ml', {value: undefined, configurable: true}))
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin === new URL(testInfo.project.use.baseURL!).origin && !url.pathname.startsWith('/api/webnn/')) {
      return route.continue()
    }
    unexpected.push(url.href)
    return route.abort()
  })

  const response = await request.post('/api/demo')
  expect(response.ok()).toBe(true)
  const {document} = await response.json()
  try {
    await page.goto('/')
    await page.locator('.doc-item').filter({hasText: 'Projet Horizon'}).click()
    await page.getByRole('button', {name: 'Paramètres du modèle'}).click()
    const models = page.getByLabel('Modèle local')
    await expect(models.locator('option[value="qwen3-4b:llamacpp"]')).toHaveText('Qwen3 4B · llama.cpp (CPU)')
    await models.selectOption('qwen3-4b:llamacpp')
    await expect(page.getByText('llama.cpp CPU disponible')).toBeVisible()
    await expect(page.getByText(/Calcul demandé/)).toHaveCount(0)
    await page.getByLabel('Format de réponse').selectOption('réponse courte')
    await page.getByRole('textbox', {name: 'Votre question'}).fill('Quel est le budget annoncé pour 2027 ?')
    await page.getByRole('button', {name: 'Envoyer la question'}).click()
    const answer = page.locator('.exchange').last()
    await expect(answer.getByText('· llama.cpp CPU')).toBeVisible({timeout: 45000})
    await expect(answer).toContainText(/240[   ]?000/)
    await expect(answer.locator('.sources button').first()).toBeVisible()
    await expect(page.getByRole('button', {name: 'Arrêter la réponse'})).toHaveCount(0)
    await page.screenshot({path: testInfo.outputPath('clair-llamacpp-cpu.png')})

    await page.getByRole('button', {name: 'Résumé', exact: true}).click()
    await expect(page.locator('.exchange')).toHaveCount(2)
    await expect(page.locator('.exchange').last().getByText('· llama.cpp CPU')).toBeVisible({timeout: 45000})
    const history = await (await request.get(`/api/documents/${document.id}/messages`)).json()
    expect(history).toHaveLength(2)
    for (const answer of history) {
      expect(answer.metrics).toMatchObject({runtime: 'llamacpp', device: 'cpu', model: 'qwen3-4b:llamacpp'})
      expect(answer.metrics.model_calls).toBeGreaterThan(0)
      expect(answer.sources.length).toBeGreaterThan(0)
      expect(answer.answer).toMatch(/\[S\d+\]/)
    }
    expect(history[1].metrics.strategy).toBe('fast')
    expect(unexpected).toEqual([])
    await testInfo.attach('réponses locales', {body: JSON.stringify(history, null, 2), contentType: 'application/json'})
  } finally {
    await request.delete(`/api/documents/${document.id}`)
  }
})
