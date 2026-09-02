<script setup lang="ts">
import { computed } from 'vue'

import type { TeacherDiagnosisWorkflow } from '@/types/teacher'

const props = defineProps<{
  workflow: TeacherDiagnosisWorkflow
}>()

const ruleHits = computed(() => {
  const pending = props.workflow.review_request?.rule_hits ?? []
  return pending.length ? pending : (props.workflow.final_result?.rule_hits ?? [])
})
const candidates = computed(() => {
  const pending = props.workflow.review_request?.candidates ?? []
  return pending.length ? pending : (props.workflow.final_result?.candidate_causes ?? [])
})
const knowledgeReferences = computed(() => {
  const pending = props.workflow.review_request?.retrieved_chunks ?? []
  return pending.length ? pending : (props.workflow.final_result?.knowledge_references ?? [])
})
const approvedKnowledgeReferences = computed(() =>
  knowledgeReferences.value.filter((item) => item.metadata?.review_status === 'approved'),
)
const unverifiedKnowledgeReferences = computed(() =>
  knowledgeReferences.value.filter((item) => item.metadata?.review_status !== 'approved'),
)
const explanation = computed(() => {
  const finalResult = props.workflow.final_result
  const aiResult = props.workflow.review_request?.ai_result
  const deterministicResult = props.workflow.review_request?.deterministic_result
  if (finalResult?.summary) return finalResult
  if (aiResult?.summary) return aiResult
  if (deterministicResult?.summary) return deterministicResult
  return finalResult ?? aiResult ?? deterministicResult ?? null
})
const limitations = computed(() => {
  if (props.workflow.final_result) return props.workflow.final_result.limitations ?? []
  const aiLimitations = props.workflow.review_request?.ai_result?.limitations ?? []
  if (aiLimitations.length) return aiLimitations
  return props.workflow.review_request?.deterministic_result?.limitations ?? []
})

function scorePercent(score: number): number {
  return Math.min(100, Math.max(0, Math.round(score <= 1 ? score * 100 : score)))
}

function actionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订并批准', reject: '驳回' }[action]
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="workflow-evidence-summary">
    <div class="workflow-summary-line">
      <div>
        <small>待确认的诊断结果</small>
        <strong>{{ explanation?.summary || '尚未生成诊断摘要' }}</strong>
      </div>
      <span>需要教师决定</span>
    </div>

    <div class="workflow-proof-columns">
      <section>
        <h4>设备表现</h4>
        <ul v-if="ruleHits.length">
          <li v-for="hit in ruleHits" :key="hit.rule_id">
            <b>{{ hit.summary }}</b>
            <small v-if="hit.evidence.length">
              {{
                hit.evidence
                  .map((item) => `${item.fact}：${item.observed_value ?? '已观测到'}`)
                  .join('；')
              }}
            </small>
          </li>
        </ul>
        <p v-else class="workflow-missing">暂无可供确认的设备表现。</p>
      </section>

      <section>
        <h4>可能原因</h4>
        <ul v-if="candidates.length">
          <li v-for="candidate in candidates" :key="candidate.cause_id">
            <b>{{ candidate.name }}</b
            ><em>可能性 {{ scorePercent(candidate.score) }}%</em>
          </li>
        </ul>
        <p v-else class="workflow-missing">当前还没有可靠的原因候选。</p>
      </section>

      <section>
        <h4>参考资料</h4>
        <ul v-if="approvedKnowledgeReferences.length">
          <li v-for="reference in approvedKnowledgeReferences" :key="reference.chunk_id">
            <b>{{ reference.title }}</b
            ><em>已审核</em>
          </li>
        </ul>
        <p v-else class="workflow-missing">本次未匹配到已审核的结构化案例。</p>
      </section>
    </div>

    <div v-if="unverifiedKnowledgeReferences.length" class="workflow-unverified-knowledge">
      <strong
        >有 {{ unverifiedKnowledgeReferences.length }} 份资料未通过审核，未用于本次诊断。</strong
      >
    </div>

    <div v-if="limitations.length" class="workflow-limitations teacher-workflow-limitations">
      <strong>审核时请重点确认</strong>
      <ul>
        <li v-for="item in limitations" :key="item">{{ item }}</li>
      </ul>
    </div>

    <div v-if="workflow.reviews?.length" class="workflow-review-history">
      <strong>审核历史</strong>
      <ol>
        <li v-for="review in workflow.reviews ?? []" :key="review.id">
          <b>{{ actionLabel(review.action) }}</b>
          <time>{{ formatDate(review.created_at) }}</time>
          <span>{{ review.comment || '未填写审核说明' }}</span>
        </li>
      </ol>
    </div>
  </div>
</template>
