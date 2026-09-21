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
  student_username: string
  student_password: string
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
  await page.getByText('测试设备演示', { exact: true }).click()
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
  await page.getByRole('button', { name: '检查当前数据', exact: true }).click()
  const response = await started
  expect(response.status()).toBe(201)
  const workflow = await response.json()
  expect(workflow.status).toBe('waiting_feedback')
  await expect(page.getByRole('button', { name: '仍未解决', exact: true })).toBeVisible()
  const persisted = await backend.snapshot()
  expect(persisted.migration).toBe('20260920_0033')
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

test('account login uses no device secret and explicitly ends its own experiment', async ({
  page,
  backend,
}) => {
  const requests: Array<Record<string, string>> = []
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/student/')) requests.push(request.headers())
  })
  await page.goto('/login')
  await page.getByPlaceholder('学生账号', { exact: true }).fill(backend.manifest.student_username)
  await page.getByPlaceholder('学生密码', { exact: true }).fill(backend.manifest.student_password)
  const authenticated = page.waitForResponse(
    (response) =>
      response.url().endsWith('/api/v1/auth/session') && response.request().method() === 'POST',
  )
  await page.getByRole('button', { name: '验证学生账号', exact: true }).click()
  const accountResponse = await authenticated
  expect(accountResponse.status()).toBe(200)
  expect((await accountResponse.json()).roles).toContain('student')
  await expect(page.getByRole('button', { name: '进入所选实验', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '进入所选实验', exact: true }).click()
  await expect(page).toHaveURL(/\/student$/)
  await expect(page.getByRole('button', { name: '结束本次实验', exact: true })).toBeEnabled()
  expect(requests.some((h) => h.authorization?.startsWith('Bearer '))).toBe(true)
  expect(requests.every((h) => !h['x-device-token'])).toBe(true)
  await page.getByRole('button', { name: '结束本次实验', exact: true }).click()
  await expect(page).toHaveURL(/\/login$/)
  const stored = await page.evaluate(() => sessionStorage.getItem('xinjian-student-device-session'))
  expect(stored).toBeNull()
})

test('teacher releases revoked student occupancy with lost-response recovery, next student starts', async ({
  page,
  context,
  backend,
}) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  // Seed only this fixture's random schema; authorization and release use real HTTP.
  await exec(
    python,
    [
      '-c',
      `
import json,os
from pathlib import Path
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.cli.browser_integration_fixture import scoped_url
from app.models import User,Enrollment,ExperimentSession,ExperimentAssignment,DeviceBinding
from app.core.security import hash_password
from app.services.rbac import assign_role,ensure_rbac_catalog
m=json.loads(Path(os.environ['AUDIT_MANIFEST']).read_text())
e=create_engine(scoped_url(os.environ['XINJIAN_EVAL_POSTGRES_DSN'],m['schema']))
with Session(e) as db:
 s=db.get(ExperimentSession,m['session_id']);a=db.get(ExperimentAssignment,s.experiment_assignment_id)
 db.scalar(select(Enrollment).where(Enrollment.user_id==s.student_user_id)).status='withdrawn'
 old=db.get(User,s.student_user_id);old.is_active=False
 new=User(username='handover-student',display_name='合成接班学生',password_hash=hash_password('handover-only',iterations=1000),is_test_data=True)
 db.add(new);db.flush();assign_role(db,new,ensure_rbac_catalog(db)['student'])
 db.add(Enrollment(user_id=new.id,class_id=a.class_id,status='active'))
 binding=db.scalar(select(DeviceBinding).where(DeviceBinding.device_id==s.device_id));binding.student_user_id=new.id
 db.commit()
e.dispose()
`,
    ],
    {
      cwd: backendDir,
      env: { ...process.env, AUDIT_MANIFEST: join(backend.controlDir, 'manifest.json') },
    },
  )
  await page.goto('/teacher/login')
  await page.getByPlaceholder('教师用户名', { exact: true }).fill('synthetic-teacher')
  await page.getByPlaceholder('密码', { exact: true }).fill('synthetic-evaluation-login')
  await page.getByRole('button', { name: '进入教师端', exact: true }).click()
  await expect(page).toHaveURL(/\/teacher$/)
  await page.getByText('管理实验会话与设备交接', { exact: true }).click()
  const panel = page.getByRole('region', { name: '实验设备占用管理' })
  await expect(panel.getByRole('button', { name: '结束占用', exact: true })).toBeVisible()
  await test
    .info()
    .attach('session-management', { body: await panel.screenshot(), contentType: 'image/png' })
  const sent: Array<{ request_id: string; expected_version: number }> = []
  page.on('request', (r) => {
    if (r.url().endsWith('/release') && r.method() === 'POST') sent.push(r.postDataJSON())
  })
  await page.route(
    '**/teacher/experiment-sessions/*/release',
    async (route) => {
      const saved = await route.fetch()
      expect(saved.status()).toBe(200)
      await route.abort('failed')
    },
    { times: 1 },
  )
  await panel.getByRole('button', { name: '结束占用', exact: true }).click()
  await page
    .getByPlaceholder('请填写原因，例如：学生资格已撤销，需要交接设备')
    .fill('选课资格撤销，交接给下一位学生')
  await page.getByRole('button', { name: '确认结束占用', exact: true }).click()
  await expect(panel.getByRole('button', { name: '继续确认原操作', exact: true })).toBeVisible()
  for (const name of ['课堂概览', '资料与审核']) {
    await page.getByRole('tab', { name, exact: true }).click()
    await expect(page.getByRole('status', { name: '设备交接恢复提示' })).toBeVisible()
    await expect(
      page.getByRole('button', { name: '查看待确认的设备交接', exact: true }),
    ).toBeVisible()
  }
  expect(sent).toHaveLength(1)
  await page.getByRole('button', { name: '查看待确认的设备交接', exact: true }).click()
  await expect(panel.getByRole('button', { name: '继续确认原操作', exact: true })).toBeVisible()
  expect(sent).toHaveLength(1)
  await page.reload()
  await panel.getByRole('button', { name: '继续确认原操作', exact: true }).click()
  await expect(panel.getByText('当前没有实验占用', { exact: true })).toBeVisible()
  expect(sent).toHaveLength(2)
  expect(sent[1]).toEqual(sent[0])

  const nextPage = await context.newPage()
  await nextPage.goto('/login')
  await nextPage.getByPlaceholder('学生账号', { exact: true }).fill('handover-student')
  await nextPage.getByPlaceholder('学生密码', { exact: true }).fill('handover-only')
  await nextPage.getByRole('button', { name: '验证学生账号', exact: true }).click()
  await nextPage.getByText('选择实验任务', { exact: true }).click()
  await nextPage.getByRole('option', { name: '合成作业（测试）', exact: true }).click()
  await nextPage.getByText('选择设备', { exact: true }).click()
  await nextPage.getByRole('option', { name: '合成评测设备', exact: true }).click()
  await nextPage.getByRole('button', { name: '开始所选实验', exact: true }).click()
  await expect(nextPage).toHaveURL(/\/student$/)
  await expect(nextPage.getByRole('button', { name: '结束本次实验', exact: true })).toBeEnabled()
  const verified = await exec(
    python,
    [
      '-c',
      `
import json,os
from pathlib import Path
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from app.cli.browser_integration_fixture import scoped_url
from app.models import ExperimentSession,AuditEvent,ExperimentSessionCommand
m=json.loads(Path(os.environ['AUDIT_MANIFEST']).read_text())
e=create_engine(scoped_url(os.environ['XINJIAN_EVAL_POSTGRES_DSN'],m['schema']))
with Session(e) as db:
 old=db.get(ExperimentSession,m['session_id']);assert old.status=='cancelled' and old.version_no==2
 active=list(db.scalars(select(ExperimentSession).where(ExperimentSession.status=='active')))
 assert len(active)==1 and active[0].student_user_id!=old.student_user_id
 assert len(list(db.scalars(select(ExperimentSessionCommand).where(ExperimentSessionCommand.session_id==old.id))))==1
 assert len(list(db.scalars(select(AuditEvent).where(AuditEvent.action=='experiment_session.release'))))==1
 print('handover database invariants verified')
e.dispose()
`,
    ],
    {
      cwd: backendDir,
      env: { ...process.env, AUDIT_MANIFEST: join(backend.controlDir, 'manifest.json') },
    },
  )
  expect(verified.stdout).toContain('handover database invariants verified')
  expect(pageErrors).toEqual([])
})

test('teaching references are visible from persisted package guidance and survive refresh', async ({
  page,
  backend,
}, testInfo) => {
  await login(page, backend)
  await ingestAndDiagnose(page, backend)
  const reference = page.locator('.teaching-reference').first()
  await expect(reference).toBeVisible()
  await reference.locator('summary').click()
  await expect(reference).toContainText('测试资料，待硬件与教师确认')
  await expect(reference).toContainText('版本 2.0.3')
  await expect(reference).toContainText('不是实测结果')
  await expect(reference).toContainText('不代表已经执行')
  const before = await reference.innerText()
  const snapshot = await backend.snapshot()
  await page.reload()
  await page.locator('.teaching-reference').first().locator('summary').click()
  await expect(page.locator('.teaching-reference').first()).toHaveText(before, {
    useInnerText: true,
  })
  const after = await backend.snapshot()
  expect(after.feedback).toEqual(snapshot.feedback)
  expect(after.ai_call_ids).toEqual(snapshot.ai_call_ids)
  expect(after.workflows).toEqual(snapshot.workflows)
  await testInfo.attach('teaching-reference-panel', {
    body: await page.getByRole('region', { name: '当前问题的排查与反馈' }).screenshot(),
    contentType: 'image/png',
  })
})

test('new-data checks preserve identity after response loss and do not rerun on refresh', async ({
  page,
  backend,
}, testInfo) => {
  await login(page, backend)
  await ingestAndDiagnose(page, backend)
  const before = await backend.snapshot()
  await page.getByRole('button', { name: '用最新数据重新检查', exact: true }).click()
  await expect(
    page
      .getByLabel('检查时效与范围')
      .getByText('暂无新的检查依据，保留上次诊断。', { exact: true }),
  ).toBeVisible()
  const unchanged = await backend.snapshot()
  expect(unchanged.workflows).toEqual(before.workflows)
  expect(unchanged.ai_call_ids).toEqual(before.ai_call_ids)
  const now = new Date().toISOString()
  const response = await page.request.post(`${backendURL}/api/v1/device/ingest`, {
    headers: headers(backend),
    data: {
      protocolVersion: '1.0',
      schemaVersion: '1',
      requestId: crypto.randomUUID(),
      bootId: 'recheck-browser',
      sequenceNo: 2,
      sentAt: now,
      isTestData: true,
      records: backend.manifest.records.map((record) => ({ ...record, occurredAt: now })),
    },
  })
  expect(response.status()).toBe(201)
  const sent: unknown[] = []
  const endpoint = `/diagnosis-workflows/devices/${backend.manifest.device_key}`
  page.on('request', (r) => {
    if (r.url().endsWith(endpoint) && r.method() === 'POST') sent.push(r.postDataJSON())
  })
  await page.route(
    `**${endpoint}`,
    async (route) => {
      const saved = await route.fetch()
      expect(saved.status()).toBe(201)
      await route.abort('failed')
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: '用最新数据重新检查', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认上次检查结果', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '数据记录', exact: true }).click()
  await expect(page.getByRole('status', { name: '检查结果待确认' })).toBeVisible()
  await page.getByRole('tab', { name: '实验参考', exact: true }).click()
  await expect(page.getByRole('status', { name: '检查结果待确认' })).toBeVisible()
  await page.getByRole('tab', { name: '当前实验', exact: true }).click()
  const committed = await backend.snapshot()
  expect(committed.workflows).toHaveLength(before.workflows.length + 1)
  await page.reload()
  await expect(page.getByRole('button', { name: '确认上次检查结果', exact: true })).toBeVisible()
  expect(sent).toHaveLength(1)
  await page.getByRole('button', { name: '确认上次检查结果', exact: true }).click()
  await expect(page.getByRole('button', { name: '用最新数据重新检查', exact: true })).toBeVisible()
  expect(sent).toHaveLength(2)
  expect(sent[1]).toEqual(sent[0])
  const after = await backend.snapshot()
  expect(after.workflows).toEqual(committed.workflows)
  expect(after.ai_call_ids).toEqual(committed.ai_call_ids)
  await page.getByText('本次诊断依据与记录', { exact: true }).click()
  await expect(page.getByRole('region', { name: '本次检查依据' })).toContainText(
    '重新检查只分析已上传数据',
  )
  await testInfo.attach('recheck-comparison', {
    body: await page.getByRole('region', { name: '本次检查依据' }).screenshot(),
    contentType: 'image/png',
  })
})
