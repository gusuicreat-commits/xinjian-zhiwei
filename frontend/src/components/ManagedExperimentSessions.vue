<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessageBox, ElTable, ElTableColumn } from 'element-plus'
import {
  getManagedSessions,
  authorizedPendingReleases,
  releaseManagedSession,
  type ManagedSession,
  type PendingRelease,
} from '@/api/sessionManagement'

const props = defineProps<{ accessToken: string; userId: string }>()
const sessions = ref<ManagedSession[]>([])
const pending = ref<PendingRelease[]>([])
const error = ref('')
const loading = ref(false)
const acting = ref(false)
const authorized = ref(false)
let generation = 0
let alive = true
onBeforeUnmount(() => {
  alive = false
  generation++
})
const rows = computed(() => [
  ...sessions.value,
  ...pending.value
    .filter((p) => !sessions.value.some((s) => s.id === p.session.id))
    .map((p) => p.session),
])
const command = (id: string) => pending.value.find((p) => p.session.id === id)
async function refresh() {
  const run = ++generation
  const token = props.accessToken
  const userId = props.userId
  loading.value = true
  authorized.value = false
  error.value = ''
  sessions.value = []
  pending.value = []
  try {
    const data = await getManagedSessions(token)
    if (run !== generation || token !== props.accessToken || userId !== props.userId) return
    const recovered = await authorizedPendingReleases(token, userId)
    if (run !== generation || token !== props.accessToken || userId !== props.userId) return
    sessions.value = data
    pending.value = recovered
    authorized.value = true
  } catch (e) {
    if (run !== generation) return
    const status = isAxiosError(e) ? e.response?.status : undefined
    error.value =
      status === 401
        ? '登录已失效，请重新登录。'
        : status === 403
          ? '当前账号无权管理实验占用。'
          : '占用列表暂时无法读取，请刷新后再操作。'
  } finally {
    if (run === generation) loading.value = false
  }
}
function releaseById(id: string) {
  const session = rows.value.find((item) => item.id === id)
  if (session) void release(session)
}
async function release(session: ManagedSession) {
  if (acting.value || !authorized.value) return
  acting.value = true
  const token = props.accessToken
  const userId = props.userId
  try {
    const original = command(session.id)
    const reason =
      original?.payload.reason ??
      (
        await ElMessageBox.prompt(
          `结束 ${session.student_name} 在“${session.assignment_title}”中对 ${session.display_name || session.device_id} 的占用。记录将保留，不代表实验完成或故障解决。`,
          '结束设备占用',
          {
            inputPlaceholder: '请填写原因，例如：学生资格已撤销，需要交接设备',
            inputValidator: (value) => Boolean(value?.trim()) || '请填写原因',
            confirmButtonText: '确认结束占用',
            cancelButtonText: '取消',
          },
        )
      ).value
    if (!alive || token !== props.accessToken || userId !== props.userId) return
    await releaseManagedSession(token, userId, original?.session ?? session, reason)
    if (token === props.accessToken && userId === props.userId) await refresh()
  } catch (e) {
    if (e === 'cancel' || e === 'close' || token !== props.accessToken || userId !== props.userId)
      return
    await refresh()
    const status = isAxiosError(e) ? e.response?.status : undefined
    if (status === 401 || status === 403) {
      sessions.value = []
      pending.value = []
      authorized.value = false
      error.value =
        status === 401 ? '登录已失效，请重新登录。' : '权限已变化，已停止操作并清除列表。'
    } else
      error.value =
        status === 409
          ? '会话状态已变化，请查看刷新后的列表再决定。'
          : status === 422
            ? '结束占用的原因或请求无效，请检查后重新操作。'
            : '操作结果尚未确认，请点击“继续确认原操作”；系统会沿用原提交记录。'
  } finally {
    acting.value = false
  }
}
watch(
  () => [props.accessToken, props.userId],
  () => void refresh(),
  { immediate: true },
)
</script>

<template>
  <section class="session-management" aria-label="实验设备占用管理">
    <h2>实验设备占用</h2>
    <p>按原班级管理尚未结束的实验；学生停用或撤销资格后仍可处理交接。</p>
    <el-button :loading="loading" :disabled="acting" @click="refresh">刷新占用列表</el-button>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" />
    <el-table v-if="authorized" :data="rows" row-key="id" empty-text="当前没有实验占用">
      <el-table-column prop="class_name" label="班级" />
      <el-table-column prop="student_name" label="学生" />
      <el-table-column prop="assignment_title" label="任务" />
      <el-table-column prop="device_id" label="设备" />
      <el-table-column label="状态"
        ><template #default="{ row }"
          >{{ command(row.id) ? '操作待确认' : '使用中'
          }}{{ row.is_test_data ? ' · 测试' : '' }}</template
        ></el-table-column
      >
      <el-table-column label="操作" width="170"
        ><template #default="{ row }">
          <el-button :disabled="acting || loading" @click="releaseById(row.id)">{{
            command(row.id) ? '继续确认原操作' : '结束占用'
          }}</el-button>
        </template></el-table-column
      >
    </el-table>
  </section>
</template>

<style scoped>
.session-management {
  padding: 24px;
  margin: 24px 0;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
}
.session-management p {
  color: #64748b;
  margin: 12px 0;
}
</style>
