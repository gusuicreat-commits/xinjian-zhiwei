export interface DeviceCredentials {
  deviceId: string
  deviceToken: string
}

export interface StudentSession {
  device_id: string
  display_name: string | null
  auth_mode: 'device_credential_placeholder'
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
}

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

export interface StudentDashboard {
  generated_at: string
  task: CurrentTask
  device: StudentDevice
  logs: StudentLog[]
  readings: StudentReading[]
  diagnosis: StudentDiagnosis | null
  guidance: StudentGuidance[]
  feedback: StudentFeedback | null
}
