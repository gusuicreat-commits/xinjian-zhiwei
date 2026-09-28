export interface MemorySource {
  kind: 'package' | 'package_case' | 'case' | 'unresolved_case'
  id: string
  version: string | null
  hash: string | null
  package_id?: string | null
}
export interface MemoryContext {
  contract_version: 'memory-v1'
  available: boolean
  facts: Array<{
    kind: 'configuration'
    subject: string
    value: Record<string, unknown>
    source: MemorySource
    physical_verification: 'not_asserted'
    is_test_data: boolean
  }>
  experiences: Array<{
    source: MemorySource
    status: 'approved_reference'
    root_cause_for_this_task: 'not_confirmed'
  }>
  working: {
    workflow_id: string
    session_id: string
    diagnosis_result_id: string | null
    package_version_id: string | null
    revision: number
    active: boolean
    status: string
    evidence_ids: string[]
    evidence_truncated: boolean
    feedback: Array<{ id: string; action: string; source: 'student_report'; created_at: string }>
    feedback_truncated: boolean
    next_step: string | null
    is_test_data: boolean
  }
}
export interface MemoryEvent {
  id: string
  source: MemorySource
  reason: string
  cache_cleanup_status: string
}
export type ReviewDecision = 'no_change' | 'verify_again' | 'correct_guidance'
export interface MemoryImpact {
  diagnosis_result_id: string
  basis: string[]
  is_test_data: boolean
  review: { id: string; version: number; decision: ReviewDecision; note: string } | null
}
export interface MemoryPage<T> {
  items: T[]
  next_cursor: string | null
}
export interface CleanupPlan {
  id: string
  status: string
  plan_hash: string
  targets: Array<{ id: string; fingerprint: string; expires_at: string }>
  blocked_stores: Array<{ store: string; reason: string }>
  result: { all_copies_deleted?: boolean; items?: Array<{ id: string; result: string }> }
}
