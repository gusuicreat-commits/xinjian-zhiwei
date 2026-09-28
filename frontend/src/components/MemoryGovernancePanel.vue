<script setup lang="ts">
import { ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import {
  memoryEvents,
  memoryImpactHistory,
  memoryImpacts,
  saveMemoryReview,
  previewMemoryCleanup,
  executeMemoryCleanup,
} from '@/api/memory'
import type { CleanupPlan, MemoryEvent, MemoryImpact, ReviewDecision } from '@/types/memory'
const props = defineProps<{ accessToken: string; administrator: boolean }>()
const events = ref<MemoryEvent[]>([])
const impacts = ref<MemoryImpact[]>([])
const selected = ref<MemoryEvent | null>(null)
const eventCursor = ref<string | null>(null)
const impactCursor = ref<string | null>(null)
const busy = ref(false)
const error = ref('')
const loaded = ref(false)
const plan = ref<CleanupPlan | null>(null)
const notes = ref<Record<string, string>>({})
const decisions = ref<Record<string, ReviewDecision>>({})
const histories = ref<Record<string, Awaited<ReturnType<typeof memoryImpactHistory>>>>({})
function stopReason(reason: string) {
  if (reason === 'experiment_package.revoked') return '实验包已撤销'
  if (reason === 'restored_stop_registry') return '已按停用登记恢复限制'
  return reason
}
async function loadHistory(item: MemoryImpact) {
  const event = selected.value
  if (!event) return
  await perform(async (token, current) => {
    const result = await memoryImpactHistory(token, event.id, item.diagnosis_result_id)
    if (current()) histories.value[item.diagnosis_result_id] = result
  })
}
let generation = 0
watch(
  () => props.accessToken,
  () => {
    generation++
    histories.value = {}
    events.value = []
    impacts.value = []
    selected.value = null
    eventCursor.value = impactCursor.value = null
    plan.value = null
    notes.value = {}
    decisions.value = {}
    busy.value = false
    error.value = ''
    loaded.value = false
  },
)
async function perform(action: (token: string, current: () => boolean) => Promise<void>) {
  if (busy.value || !props.accessToken) return
  busy.value = true
  error.value = ''
  const version = generation
  const current = () => version === generation
  try {
    await action(props.accessToken, current)
  } catch (failure) {
    if (current()) {
      if (isAxiosError(failure) && [401, 403].includes(failure.response?.status ?? 0)) {
        events.value = []
        impacts.value = []
        histories.value = {}
        selected.value = null
        notes.value = {}
        decisions.value = {}
        plan.value = null
        eventCursor.value = impactCursor.value = null
        loaded.value = false
      }
      error.value = '操作未确认，请重新读取当前状态；权限变化时请重新登录。'
    }
  } finally {
    if (current()) busy.value = false
  }
}
async function loadEvents(more = false) {
  await perform(async (token, current) => {
    const page = await memoryEvents(token, more ? (eventCursor.value ?? '') : '')
    if (!current()) return
    events.value = more ? [...events.value, ...page.items] : page.items
    eventCursor.value = page.next_cursor
    loaded.value = true
    if (!more) {
      selected.value = null
      impacts.value = []
      impactCursor.value = null
    }
  })
}
async function loadImpacts(event: MemoryEvent, more = false) {
  await perform(async (token, current) => {
    const page = await memoryImpacts(token, event.id, more ? (impactCursor.value ?? '') : '')
    if (!current()) return
    selected.value = event
    impacts.value = more ? [...impacts.value, ...page.items] : page.items
    impactCursor.value = page.next_cursor
    for (const item of page.items) {
      notes.value[item.diagnosis_result_id] = item.review?.note ?? ''
      decisions.value[item.diagnosis_result_id] = item.review?.decision ?? 'verify_again'
    }
  })
}
async function submit(item: MemoryImpact) {
  const event = selected.value
  const note = notes.value[item.diagnosis_result_id]?.trim()
  if (!event || !note) return
  await perform(async (token, current) => {
    const result = await saveMemoryReview(
      token,
      event.id,
      item,
      decisions.value[item.diagnosis_result_id] ?? 'verify_again',
      note,
    )
    if (current()) item.review = result
  })
}
async function preview() {
  await perform(async (token, current) => {
    const result = await previewMemoryCleanup(token)
    if (current()) plan.value = result
  })
}
async function execute() {
  const snapshot = plan.value
  if (!snapshot) return
  await perform(async (token, current) => {
    const result = await executeMemoryCleanup(token, snapshot)
    if (current()) plan.value = result
  })
}
</script>
<template>
  <article class="memory-governance">
    <h2>知识停用与影响复核</h2>
    <p>只列出当前有权查看的关联记录。可能受影响不等于已经误诊；旧记录不会被改写。</p>
    <button :disabled="busy" @click="loadEvents()">读取停用记录</button>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="loaded && !events.length && !error">
      当前范围没有已追踪的停用记录。关联缺失的历史仍需核实。
    </p>
    <ul>
      <li v-for="event in events" :key="event.id">
        <button :disabled="busy" @click="loadImpacts(event)">
          查看{{ event.source.kind === 'package' ? '实验包' : '案例' }}
          {{ event.source.version }} 的影响
        </button>
        <p>{{ stopReason(event.reason) }}</p>
        <details>
          <summary>来源标识</summary>
          {{ event.source.id }}
        </details>
      </li>
    </ul>
    <button v-if="eventCursor" :disabled="busy" @click="loadEvents(true)">更多停用记录</button>
    <section v-if="selected">
      <h3>待复核的诊断</h3>
      <p v-if="selected.source.kind === 'case'">
        全局案例停用不代表实验包副本已撤销，相关包需要单独审核处理。
      </p>
      <p v-if="!impacts.length">当前已扫描范围没有关联诊断；未建立关联的历史不能据此排除。</p>
      <div v-for="item in impacts" :key="item.diagnosis_result_id" class="impact-item">
        <p>
          {{ item.is_test_data ? '测试诊断' : '诊断记录' }} ·
          {{ item.review ? '已有复核结果' : '待复核' }}
        </p>
        <details>
          <summary>诊断标识</summary>
          {{ item.diagnosis_result_id }}
        </details>
        <button :disabled="busy" @click="loadHistory(item)">查看当时依据</button>
        <div v-if="histories[item.diagnosis_result_id]">
          <p>以下仅供历史复核，不能作为当前操作建议。</p>
          <ul>
            <li v-for="(rule, index) in histories[item.diagnosis_result_id]!.rules" :key="index">
              {{ rule.summary }}
            </li>
          </ul>
          <p>{{ histories[item.diagnosis_result_id]!.historical_result?.summary }}</p>
        </div>
        <label
          >复核结论
          <select v-model="decisions[item.diagnosis_result_id]" :disabled="busy">
            <option value="verify_again">需要补充核验</option>
            <option value="correct_guidance">需要更正指导</option>
            <option value="no_change">无需调整</option>
          </select>
        </label>
        <label
          >判断依据<textarea
            v-model="notes[item.diagnosis_result_id]"
            :disabled="busy"
            maxlength="2000"
          />
        </label>
        <button
          :disabled="busy || !!error || !notes[item.diagnosis_result_id]?.trim()"
          @click="submit(item)"
        >
          保存复核
        </button>
      </div>
      <button v-if="impactCursor" :disabled="busy" @click="loadImpacts(selected, true)">
        继续扫描关联诊断
      </button>
    </section>
    <details v-if="administrator">
      <summary>过期缓存清理</summary>
      <p>
        仅清理计划中的过期解释缓存。诊断证据、历史、工作流恢复记录及备份的保留策略尚未确定，不会删除。
      </p>
      <button :disabled="busy" @click="preview">预览清理计划</button>
      <div v-if="plan">
        <p>本计划包含 {{ plan.targets.length }} 条缓存。</p>
        <p v-if="plan.status === 'completed'">本计划处理完成，不代表所有副本已删除。</p>
        <p v-else-if="plan.status === 'partial'">部分对象状态已变化并跳过，请查看新计划。</p>
        <button v-else :disabled="busy || !plan.targets.length" @click="execute">
          执行这份缓存清理计划
        </button>
      </div>
    </details>
  </article>
</template>
<style scoped>
.memory-governance {
  padding: 22px;
  border: 1px solid #dce5eb;
  border-radius: 14px;
  background: #fff;
}
p {
  line-height: 1.6;
}
button,
select,
textarea {
  font: inherit;
  padding: 8px 12px;
  border: 1px solid #bdcbd6;
  border-radius: 6px;
}
button {
  cursor: pointer;
  background: #f2f7fb;
  margin: 6px 0;
}
button:disabled {
  opacity: 0.55;
  cursor: default;
}
label {
  display: block;
  margin: 10px 0;
}
select,
textarea {
  display: block;
  margin-top: 6px;
  max-width: 100%;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  min-height: 80px;
}
.impact-item {
  margin: 14px 0;
  padding: 14px;
  border: 1px solid #dce5eb;
  border-radius: 8px;
}
summary {
  cursor: pointer;
  margin: 10px 0;
}
</style>
