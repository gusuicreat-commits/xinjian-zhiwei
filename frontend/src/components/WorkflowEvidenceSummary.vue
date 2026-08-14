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

function formatRrfScore(score: number): string {
  return Number.isFinite(score) ? score.toFixed(4) : '—'
}

function actionLabel(action: 'approve' | 'edit' | 'reject'): string {
  return { approve: '批准', edit: '修订并批准', reject: '驳回' }[action]
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function evidenceDetailRefs(evidence: {
  evidence_refs?: string[]
  details?: Record<string, unknown>[]
}): string[] {
  const detailRefs = (evidence.details ?? []).flatMap((detail) =>
    ['log_id', 'reading_id']
      .filter((key) => typeof detail[key] === 'string')
      .map((key) => `${key === 'log_id' ? 'log' : 'reading'}:${String(detail[key])}`),
  )
  return [...new Set([...(evidence.evidence_refs ?? []), ...detailRefs])]
}
</script>

<template>
  <div class="workflow-evidence-summary">
    <div class="workflow-summary-line">
      <strong>{{ explanation?.summary || '尚未生成自然语言诊断摘要' }}</strong>
      <span v-if="workflow.final_result?.rules_preserved">规则已保留</span>
    </div>

    <dl class="workflow-version-grid">
      <div>
        <dt>规则</dt>
        <dd>{{ workflow.rule_engine_version || '—' }}</dd>
      </div>
      <div>
        <dt>故障树</dt>
        <dd>{{ workflow.fault_tree_version || '—' }}</dd>
      </div>
      <div>
        <dt>嵌入</dt>
        <dd>{{ workflow.embedding_version || '—' }}</dd>
      </div>
      <div>
        <dt>模型</dt>
        <dd>{{ workflow.model_id || '未调用' }}</dd>
      </div>
      <div>
        <dt>恢复次数</dt>
        <dd>{{ workflow.resume_count ?? 0 }}</dd>
      </div>
    </dl>

    <div v-if="workflow.node_trace.length" class="workflow-trace teacher-workflow-trace">
      <span
        v-for="(node, index) in workflow.node_trace"
        :key="`${node}-${index}`"
        :class="{
          failed: workflow.node_metrics?.some(
            (metric) => metric.node === node && metric.status === 'failed',
          ),
        }"
      >
        {{ node }}
        <small v-if="workflow.node_metrics?.find((metric) => metric.node === node)">
          {{
            workflow.node_metrics.find((metric) => metric.node === node)?.duration_ms.toFixed(1)
          }}ms
        </small>
      </span>
    </div>

    <div class="workflow-proof-columns">
      <section>
        <h4>规则 / 日志证据</h4>
        <ul v-if="ruleHits.length">
          <li v-for="hit in ruleHits" :key="hit.rule_id">
            <code>{{ hit.rule_id }}</code>
            <b>{{ hit.summary }}</b>
            <small v-if="hit.evidence.length">
              {{
                hit.evidence
                  .map((item) => {
                    const refs = evidenceDetailRefs(item)
                    return `${item.fact}=${item.observed_value ?? '已命中'}${refs.length ? ` [${refs.join('、')}]` : ''}`
                  })
                  .join('；')
              }}
            </small>
          </li>
        </ul>
        <p v-else class="workflow-missing">未记录可引用的规则命中。</p>
      </section>

      <section>
        <h4>故障树候选</h4>
        <ul v-if="candidates.length">
          <li v-for="candidate in candidates" :key="candidate.cause_id">
            <b>{{ candidate.name }}</b
            ><em>{{ scorePercent(candidate.score) }}%</em>
            <small>{{ candidate.evidence_refs.join('、') || '缺少稳定证据引用' }}</small>
          </li>
        </ul>
        <p v-else class="workflow-missing">未记录故障树候选。</p>
      </section>

      <section>
        <h4>已审核知识来源</h4>
        <ul v-if="approvedKnowledgeReferences.length">
          <li v-for="reference in approvedKnowledgeReferences" :key="reference.chunk_id">
            <b>{{ reference.title }}</b
            ><em>RRF {{ formatRrfScore(reference.score) }}</em>
            <code>{{ reference.source_id }} / {{ reference.chunk_id }}</code>
            <small> 版本 {{ reference.metadata?.source_version || '—' }} · 已审核 </small>
          </li>
        </ul>
        <p v-else-if="workflow.needs_rag" class="workflow-missing danger">
          需要 RAG，但没有可采用的已审核来源。
        </p>
        <p v-else class="workflow-missing">本次证据分支未触发 RAG。</p>
      </section>
    </div>

    <div v-if="unverifiedKnowledgeReferences.length" class="workflow-unverified-knowledge">
      <strong>未验证来源（不可作为诊断依据）</strong>
      <ul>
        <li v-for="reference in unverifiedKnowledgeReferences" :key="reference.chunk_id">
          <span>{{ reference.title }}</span>
          <code>{{ reference.source_id }} / {{ reference.chunk_id }}</code>
          <em>RRF {{ formatRrfScore(reference.score) }}</em>
        </li>
      </ul>
    </div>

    <div v-if="workflow.retrieval_audit?.query" class="workflow-retrieval-audit">
      <strong>RAG 检索审计</strong>
      <span>查询：{{ workflow.retrieval_audit.query }}</span>
      <small>
        命中 {{ workflow.retrieval_audit.top_k ?? 0 }} · 被结果采用
        {{ workflow.retrieval_audit.adopted_evidence_refs?.length ?? 0 }}
      </small>
    </div>

    <div v-if="limitations.length" class="workflow-limitations teacher-workflow-limitations">
      <strong>限制 / 待补证据</strong>
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
