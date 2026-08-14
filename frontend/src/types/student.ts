import type { DiagnosisWorkflowRecord } from '@/types/workflow'

export interface DeviceCredentials {
  deviceId: string
  deviceToken: string
  experimentSessionId?: string
}

export interface StudentSession {
  device_id: string
  display_name: string | null
  auth_mode: 'device_credential_placeholder'
  student_user_id: string | null
  experiment_session_id: string | null
  experiment_assignment_id: string | null
  notice: string
}

export interface CurrentTask {
  configured: boolean
  title: string | null
  template_id: string | null
  notice: string
}

export interface StudentDevice {
  device_id: string
  display_name: string | null
  status: 'online' | 'offline' | 'never_seen'
  last_seen_at: string | null
  firmware_version: string | null
  is_test_fixture: boolean
}

export interface StudentLog {
  id: string
  level: string
  message: string
  event_code: string | null
  occurred_at: string
  is_test_data: boolean
}

export interface StudentReading {
  id: string
  sensor_type: string
  metric_key: string
  value: number
  unit: string | null
  observed_at: string
  is_test_data: boolean
}

export interface EvidenceItem {
  fact: string
  observed_value: number
  details: Record<string, unknown>[]
}

export interface DiagnosisMatch {
  rule_id: string
  error_type: string
  priority: number
  summary: string
  evidence: EvidenceItem[]
}

export interface StudentDiagnosis {
  id: string
  evaluated_at: string
  matches: DiagnosisMatch[]
  evidence: Array<{ rule_id: string; items: EvidenceItem[] }>
  is_test_data: boolean
  deterministic_result: DiagnosisCore | null
  explanation: DeterministicExplanation | null
  ai_enhancement: AIEnhancementState | null
}

export interface DiagnosisCore {
  diagnosis_result_id: string
  primary_error_code: string | null
  summary: string
  confidence: number
  evidence: string[]
  possible_causes: string[]
  suggested_steps: string[]
  hint_level: number
  need_teacher_help: boolean
  rule_ids: string[]
  knowledge_chunk_ids: string[]
  limitations: string[]
}

export interface DeterministicExplanation {
  title: string
  summary: string
  evidence: string[]
  possible_causes: string[]
  steps: string[]
  hint_level: number
  need_teacher_help: boolean
  limitations: string[]
  provenance: 'rules_and_reviewed_knowledge'
}

export interface AIEnhancementState {
  status:
    'disabled' | 'skipped' | 'cache_hit' | 'local_success' | 'cloud_success' | 'failed_fallback'
  trigger_reason: string
  route: string
  route_path: string
  cache_status: 'not_checked' | 'miss' | 'hit'
  fallback_reason?: string | null
  call_record_id?: string | null
}

export interface AIKnowledgeReference {
  chunk_id: string
  source_key: string
  source_title: string
  source_type: string | null
  source_uri: string | null
  source_version: string | null
  locator: Record<string, unknown>
  content: string
  similarity: number
  review_status: 'approved'
  retrieval_scores: Record<string, number>
  is_test_data: boolean
}

export interface AIStructuredExplanation {
  error_type: string
  summary: string
  evidence: string[]
  possible_causes: Array<{
    cause: string
    confidence: number
    knowledge_chunk_ids: string[]
  }>
  steps: string[]
  hint_level: number
  need_teacher_help: boolean
  limitations: string[]
}

export interface AIExplanationResponse {
  call_record_id: string
  diagnosis_result_id: string
  status: 'skipped' | 'succeeded' | 'failed'
  mode: 'rules_only' | 'ai_enhanced'
  provider_configured: boolean
  rules_preserved: boolean
  explanation: AIStructuredExplanation | null
  knowledge_references: AIKnowledgeReference[]
  notice: string
  enhancement_status:
    'disabled' | 'skipped' | 'cache_hit' | 'local_success' | 'cloud_success' | 'failed_fallback'
  trigger_reason: string
  route: string
  route_path: string
  deterministic_result: DeterministicExplanation | null
}

export interface AIStatus {
  framework_ready: boolean
  provider_configured: boolean
  embedding_client_configured: boolean
  require_knowledge: boolean
  provider: string | null
  model: string | null
  transport: string
  prompt_version: string
  notice: string
  ai_enabled: boolean
  local_configured: boolean
  cloud_configured: boolean
  thinking_enabled: boolean
  production_route: string
}

export type DiagnosisWorkflow = DiagnosisWorkflowRecord

export interface RankedCause {
  cause_id: string
  title: string
  score: number
  confidence: 'low' | 'medium' | 'high'
  evidence: Array<{
    fact: string
    description: string
    weight: number
    observed_value: number
    details: Record<string, unknown>[]
  }>
}

export interface GuidanceHint {
  cause_id: string
  level: 1 | 2 | 3 | 4
  text: string
}

export interface StudentGuidance {
  id: string
  tree_id: string
  tree_title: string
  tree_status: string
  hint_level: number
  failure_count: number
  teacher_intervention_required: boolean
  ranked_causes: RankedCause[]
  hints: GuidanceHint[]
  is_test_data: boolean
}

export type FeedbackAction = 'resolved' | 'unresolved' | 'request_teacher_help'

export interface StudentFeedback {
  id: string
  action: FeedbackAction
  note: string | null
  is_test_data: boolean
  created_at: string
}

export interface StudentIntervention {
  id: string
  status: 'open' | 'claimed' | 'resolved' | 'unconfirmed' | 'closed'
  version_no: number
  assigned_teacher_user_id: string | null
  resolution_summary: string | null
  updated_at: string
}

export interface DeviceStateExplanation {
  status_title: string
  status_summary: string
  meaning: string
  next_step: string
  source: 'rule' | 'ai'
  technical_details: {
    device: {
      status: 'online' | 'offline' | 'never_seen'
      last_seen_at: string | null
      firmware_version: string | null
    }
    error_code: string | null
    error_codes: string[]
    retry_count?: number
    logs: Array<{
      id: string
      level: string
      message: string
      event_code: string | null
      occurred_at: string
    }>
    sensor_readings: Array<{
      id: string
      sensor_type: string
      metric_key: string
      value: number
      unit: string | null
      observed_at: string
    }>
    rule_hits: DiagnosisMatch[]
    fault_tree_evidence: Array<{
      tree_id: string
      tree_title: string
      tree_status: string
      hint_level: number
      failure_count: number
      ranked_causes: RankedCause[]
    }>
  }
}

export interface StudentDashboard {
  generated_at: string
  task: CurrentTask
  device: StudentDevice
  logs: StudentLog[]
  readings: StudentReading[]
  diagnosis: StudentDiagnosis | null
  guidance: StudentGuidance[]
  feedback: StudentFeedback | null
  intervention: StudentIntervention | null
  ai_status: AIStatus
  ai_explanation: AIExplanationResponse | null
  device_state_explanation: DeviceStateExplanation
  episode: {
    id: string
    status: 'open' | 'escalated' | 'resolved'
    primary_error_code: string
    started_at: string
    last_seen_at: string
    failure_count: number
    current_hint_level: number
    ai_call_count: number
  } | null
}
