import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'

import { expect, test as base, type Page } from '@playwright/test'

const exec = promisify(execFile)
const backendDir = resolve(process.cwd(), '../backend')
const python = process.env.BACKEND_PYTHON!
const backendPort = Number(process.env.INTEGRATION_BACKEND_PORT ?? '18101')
const backendURL = `http://127.0.0.1:${backendPort}`
const origin = `http://127.0.0.1:${process.env.INTEGRATION_FRONTEND_PORT ?? '15173'}`
const fixtureModule = 'app.cli.browser_integration_fixture'

type Manifest = {
  schema: string
  device_key: string
  device_token: string
  session_id: string
  records: Array<Record<string, unknown>>
  is_test_data: boolean
}
type Snapshot = {
  migration: string
  workflows: Array<{
    id: string
    diagnosis_id: string
    session_id: string
    status: string
    resume_count: number
    node_trace: string[]
    is_test_data: boolean
  }>
  feedback: Array<{
    id: string
    request_id: string
    session_id: string
    action: string
    processing_status: string
    is_test_data: boolean
  }>
  evidence_ids: string[]
  ai_call_ids: string[]
}
type Backend = {
  manifest: Manifest
  controlDir: string
  snapshot: () => Promise<Snapshot>
}

async function stop(child: ChildProcess) {
  if (child.exitCode !== null) return
  const exited = once(child, 'exit')
  child.kill('SIGTERM') // Uvicorn exits; Python finally drops its own random schema.
  const timeout = setTimeout(() => child.kill('SIGKILL'), 15_000)
  try {
    const [code, signal] = await exited
    if (signal === 'SIGKILL' || (code !== null && code !== 0)) {
      throw new Error(
        'Integration fixture did not shut down cleanly; inspect temporary DB schemas.',
      )
    }
  } finally {
    clearTimeout(timeout)
  }
}

const test = base.extend<{ backend: Backend }>({
  backend: async ({}, use) => {
    const controlDir = await mkdtemp(join(tmpdir(), 'xinjian-browser-integration-'))
    let startupOutput = ''
    const child = spawn(
      python,
      [
        '-m',
        fixtureModule,
        'serve',
        '--control-dir',
        controlDir,
        '--port',
        String(backendPort),
        '--frontend-origin',
        origin,
      ],
      {
        cwd: backendDir,
        env: process.env,
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )
    child.stdout.on('data', (chunk) => {
      startupOutput += String(chunk)
    })
    child.stderr.on('data', (chunk) => {
      startupOutput += String(chunk)
    })
    let processError: Error | undefined
    child.on('error', (error) => {
      processError = error
    })
    try {
      await expect
        .poll(
          async () => {
            if (processError) throw processError
            if (child.exitCode !== null) {
              // Do not put DSNs or database error connection details in published reports.
              throw new Error(
                `Backend fixture exited (${child.exitCode}); run its CLI locally for details.`,
              )
            }
            try {
              await readFile(join(controlDir, 'manifest.json'))
              return (await fetch(`${backendURL}/api/v1/health/live`)).ok
            } catch {
              return false
            }
          },
          { timeout: 45_000, message: 'migrations, seed and real Uvicorn server must start' },
        )
        .toBe(true)
      const manifest = JSON.parse(
        await readFile(join(controlDir, 'manifest.json'), 'utf8'),
      ) as Manifest
      await use({
        manifest,
        controlDir,
        snapshot: async () => {
          const result = await exec(
            python,
            ['-m', fixtureModule, 'snapshot', '--control-dir', controlDir],
            {
              cwd: backendDir,
              env: process.env,
            },
          )
          return JSON.parse(result.stdout) as Snapshot
        },
      })
    } catch (error) {
      // Failure details stay local, outside the published browser report.
      if (!process.env.CI) process.stderr.write(startupOutput)
      throw error
    } finally {
      try {
        await stop(child)
        await exec(python, ['-m', fixtureModule, 'assert-clean', '--control-dir', controlDir], {
          cwd: backendDir,
          env: process.env,
        })
      } finally {
        await rm(controlDir, { recursive: true, force: true })
      }
    }
  },
})

async function login(page: Page, backend: Backend) {
  await page.goto('/login')
  await page.getByPlaceholder('设备 ID').fill(backend.manifest.device_key)
  await page.getByPlaceholder('设备令牌').fill(backend.manifest.device_token)
  const sessionResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/student/session') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '登录学生工作台', exact: true }).click()
  const session = await sessionResponse
  expect(session.status()).toBe(200)
  expect((await session.json()).experiment_session_id).toBe(backend.manifest.session_id)
  await expect(page).toHaveURL(/\/student$/)
  await expect(page.getByText('学生实验工作台')).toBeVisible()
}

async function ingestAndDiagnose(page: Page, backend: Backend) {
  const now = new Date().toISOString()
  const uploaded = await page.request.post(`${backendURL}/api/v1/device/ingest`, {
    headers: headers(backend),
    data: {
      protocolVersion: '1.0',
      schemaVersion: '1',
      requestId: crypto.randomUUID(),
      bootId: 'synthetic-browser-integration',
      sequenceNo: 1,
      sentAt: now,
      isTestData: true,
      records: backend.manifest.records.map((record) => ({ ...record, occurredAt: now })),
    },
  })
  expect(uploaded.status()).toBe(201) // Simulated device uses the actual network ingest endpoint.
  await page.reload()
  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/diagnosis-workflows/devices/${backend.manifest.device_key}`) &&
      response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '启动辅助诊断', exact: true }).click()
  const response = await started
  expect(response.status()).toBe(201)
  const workflow = await response.json()
  expect(workflow.status).toBe('waiting_feedback')
  await expect(page.getByRole('button', { name: '仍未解决', exact: true })).toBeVisible()
  const persisted = await backend.snapshot()
  expect(persisted.migration).toBe('20260912_0027')
  expect(persisted.evidence_ids.length).toBeGreaterThan(0)
  expect(persisted.workflows[0]).toMatchObject({
    id: workflow.id,
    is_test_data: true,
    resume_count: 0,
  })
  return workflow as { id: string; diagnosis_result_id: string }
}

function headers(backend: Backend) {
  return {
    'X-Device-ID': backend.manifest.device_key,
    'X-Device-Token': backend.manifest.device_token,
    'X-Experiment-Session-ID': backend.manifest.session_id,
  }
}

test('real browser feedback persists once, duplicate HTTP is idempotent, refresh confirms it', async ({
  page,
  backend,
}) => {
  await login(page, backend)
  const workflow = await ingestAndDiagnose(page, backend)
  const feedbackPath = `/api/v1/student/diagnoses/${workflow.diagnosis_result_id}/feedback`
  const received = page.waitForResponse(
    (response) => response.url().endsWith(feedbackPath) && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '仍未解决', exact: true }).click()
  const response = await received
  expect(response.status()).toBe(201)
  const payload = response.request().postDataJSON() as { request_id: string; action: string }
  expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/)
  await expect(page.getByText(/最近一次反馈已确认：/)).toBeVisible()
  const before = await backend.snapshot()
  expect(before.feedback).toHaveLength(1)
  expect(before.feedback[0]).toMatchObject({
    request_id: payload.request_id,
    processing_status: 'applied',
    is_test_data: true,
  })
  expect(before.workflows[0].resume_count).toBe(1)
  const duplicate = await page.request.post(`${backendURL}${feedbackPath}`, {
    headers: headers(backend),
    data: payload,
  })
  expect(duplicate.status()).toBe(201)
  expect(await duplicate.json()).toEqual(await response.json())
  expect(await backend.snapshot()).toEqual(before)
  await page.reload()
  await expect(page.getByText(/最近一次反馈已确认：/)).toBeVisible()
  expect(await backend.snapshot()).toEqual(before)
})

test('closed tab loses local request but fresh login finds server pending and resumes only on click', async ({
  page,
  context,
  backend,
}) => {
  await login(page, backend)
  const workflow = await ingestAndDiagnose(page, backend)
  await writeFile(join(backend.controlDir, 'pause-feedback'), 'synthetic outage window')
  await page.getByRole('button', { name: '仍未解决', exact: true }).click()
  await expect(page.getByText(/反馈结果尚未确认/)).toBeVisible()
  const pending = await backend.snapshot()
  expect(pending.feedback).toHaveLength(1)
  expect(pending.feedback[0].processing_status).toBe('pending')
  expect(pending.workflows[0].resume_count).toBe(0)
  await page.close()
  await rm(join(backend.controlDir, 'pause-feedback'))
  const reopened = await context.newPage()
  await reopened.goto('/login')
  expect(await reopened.evaluate(() => sessionStorage.length)).toBe(0)
  await login(reopened, backend)
  await expect(reopened.getByText('上一条反馈待确认', { exact: true })).toBeVisible()
  expect(await backend.snapshot()).toEqual(pending) // GET recovery must never advance a workflow.
  const recovered = reopened.waitForResponse(
    (response) =>
      response.url().endsWith(`/diagnoses/${workflow.diagnosis_result_id}/feedback`) &&
      response.request().method() === 'POST',
  )
  await reopened.getByRole('button', { name: '继续确认原反馈', exact: true }).click()
  const response = await recovered
  expect(response.status()).toBe(201)
  expect(response.request().postDataJSON().request_id).toBe(pending.feedback[0].request_id)
  await expect(reopened.getByText(/最近一次反馈已确认：/)).toBeVisible()
  await expect(reopened.getByText('上一条反馈待确认', { exact: true })).toHaveCount(0)
  const after = await backend.snapshot()
  expect(after.feedback).toHaveLength(1)
  expect(after.feedback[0]).toMatchObject({
    id: pending.feedback[0].id,
    processing_status: 'applied',
  })
  expect(after.workflows[0].resume_count).toBe(1)
  await reopened.reload()
  await expect(reopened.getByText(/最近一次反馈已确认：/)).toBeVisible()
  expect(await backend.snapshot()).toEqual(after)
})
