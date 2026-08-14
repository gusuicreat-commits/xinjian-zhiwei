import { mount } from '@vue/test-utils'

import type { DiagnosisWorkflowRecord } from '@/types/workflow'

import WorkflowEvidenceSummary from './WorkflowEvidenceSummary.vue'

function workflow(overrides: Partial<DiagnosisWorkflowRecord> = {}): DiagnosisWorkflowRecord {
  return {
    id: 'workflow-test',
    diagnosis_result_id: 'diagnosis-test',
    device_id: 'device-test',
    graph_thread_id: 'diagnosis:workflow-test',
    graph_version: 'langgraph-v1',
    status: 'waiting_teacher',
    current_node: 'teacher_review',
    evidence_score: 0.6,
    guidance_level: 4,
    needs_rag: true,
    needs_teacher: true,
    rule_engine_version: 'rules-v3',
    fault_tree_version: 'tree-v2',
    embedding_version: 'embedding-v1',
    model_id: null,
    node_trace: [],
    final_result: null,
    error_messages: [],
    review_request: {
      rule_hits: [],
      candidates: [],
      retrieved_chunks: [],
      ai_result: {},
      deterministic_result: {
        summary: '确定性解释',
        limitations: ['缺少稳定证据'],
      },
    },
    reviews: [],
    is_test_data: true,
    created_at: '2026-07-20T08:00:00Z',
    updated_at: '2026-07-20T08:00:00Z',
    completed_at: null,
    ...overrides,
  }
}

describe('WorkflowEvidenceSummary', () => {
  it('falls back to the deterministic explanation when AI has no summary', () => {
    const wrapper = mount(WorkflowEvidenceSummary, { props: { workflow: workflow() } })

    expect(wrapper.text()).toContain('确定性解释')
    expect(wrapper.text()).toContain('缺少稳定证据')
  })

  it('falls back from empty pending arrays and separates unapproved knowledge', () => {
    const wrapper = mount(WorkflowEvidenceSummary, {
      props: {
        workflow: workflow({
          status: 'completed',
          final_result: {
            summary: '最终解释',
            rule_hits: [
              {
                rule_id: 'rule-final',
                error_type: 'failure',
                summary: '最终规则',
                evidence: [],
              },
            ],
            candidate_causes: [
              { cause_id: 'cause-final', name: '最终候选', score: 0.5, evidence_refs: [] },
            ],
            knowledge_references: [
              {
                chunk_id: 'approved-chunk',
                source_id: 'approved-source',
                title: '已批准手册',
                score: 0.03125,
                metadata: { review_status: 'approved' },
              },
              {
                chunk_id: 'pending-chunk',
                source_id: 'pending-source',
                title: '待审核手册',
                score: 0.02,
                metadata: { review_status: 'pending' },
              },
            ],
          },
        }),
      },
    })

    expect(wrapper.text()).toContain('rule-final')
    expect(wrapper.text()).toContain('最终候选')
    expect(wrapper.findAll('.workflow-proof-columns section')[2]?.text()).toContain('已批准手册')
    expect(wrapper.findAll('.workflow-proof-columns section')[2]?.text()).not.toContain(
      '待审核手册',
    )
    expect(wrapper.find('.workflow-unverified-knowledge').text()).toContain('待审核手册')
    expect(wrapper.text()).toContain('RRF 0.0313')
    expect(wrapper.text()).toContain('RRF 0.0200')
  })
})
