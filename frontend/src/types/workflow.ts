export type DiagnosisWorkflowStatus =
  | 'created'
  | 'collecting'
  | 'deterministic_analysis'
  | 'retrieving'
  | 'ai_analysis'
  | 'waiting_teacher'
  | 'completed'
  | 'rejected'
  | 'failed'

export interface WorkflowRuleEvidence {
  fact: string
  observed_value?: number
  evidence_refs?: string[]
  details?: Record<string, unknown>[]
}

export interface WorkflowRuleHit {
  rule_id: string
  error_type: string
  summary: string
  priority?: number
  evidence: WorkflowRuleEvidence[]
}

export interface WorkflowCandidateCause {
  cause_id: string
  name: string
  score: number
  evidence_refs: string[]
}

export interface WorkflowKnowledgeReference {
  chunk_id: string
  source_id: string
  title: string
  score: number
  metadata?: {
    source_type?: string | null
    source_version?: string | null
    locator?: Record<string, unknown>
    review_status?: string
  }
}

export interface WorkflowReviewRequest {
  candidates?: WorkflowCandidateCause[]
  rule_hits?: WorkflowRuleHit[]
  retrieved_chunks?: WorkflowKnowledgeReference[]
  ai_result?: WorkflowExplanation | null
  deterministic_result?: WorkflowExplanation | null
  instruction?: string
}

export interface WorkflowExplanation {
  summary?: string
  evidence?: string[]
  possible_causes?: Array<string | { cause?: string; confidence?: number }>
  steps?: string[]
  limitations?: string[]
}

export interface WorkflowFinalResult extends WorkflowExplanation {
  rules_preserved?: boolean
  rule_hits?: WorkflowRuleHit[]
  knowledge_references?: WorkflowKnowledgeReference[]
  candidate_causes?: WorkflowCandidateCause[]
  evidence_refs?: string[]
  evidence_score?: number
  guidance_level?: number
  teacher_reviewed?: boolean
}

export interface WorkflowReview {
  id: string
  reviewer_user_id: string
  action: 'approve' | 'edit' | 'reject'
  comment: string | null
  edited_result: WorkflowExplanation | null
  created_at: string
}

export interface WorkflowNodeMetric {
  node: string
  duration_ms: number
  status: 'succeeded' | 'failed'
}

export interface WorkflowRetrievalAudit {
  query?: string | null
  top_k?: number
  matches?: Array<{ chunk_id?: string; source_id?: string; score?: number }>
  adopted_evidence_refs?: string[]
}

export interface DiagnosisWorkflowRecord {
  id: string
  diagnosis_id?: string
  diagnosis_result_id: string | null
  device_id: string
  student_user_id?: string
  experiment_session_id?: string
  graph_thread_id: string
  graph_version: string
  status: DiagnosisWorkflowStatus
  current_node: string | null
  evidence_score: number | null
  guidance_level: number | null
  needs_rag: boolean
  needs_teacher: boolean
  rule_engine_version: string | null
  fault_tree_version: string | null
  embedding_version: string | null
  model_id: string | null
  node_trace: string[]
  node_metrics?: WorkflowNodeMetric[]
  retrieval_audit?: WorkflowRetrievalAudit | null
  resume_count?: number
  final_result: WorkflowFinalResult | null
  error_messages: string[]
  review_request?: WorkflowReviewRequest | null
  reviews?: WorkflowReview[]
  is_test_data: boolean
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface DiagnosisWorkflowMetrics {
  total: number
  completed: number
  waiting_teacher: number
  rejected: number
  failed: number
  in_progress: number
  reviewed: number
  edit_rate: number
  reject_rate: number
  needs_rag_count: number
  resume_count: number
  average_node_duration_ms: number | null
  ai_call_count: number
  ai_input_tokens: number
  ai_output_tokens: number
  ai_estimated_cost: number
  student_feedback_count: number
  student_resolved_count: number
  student_resolution_rate: number | null
}
