export interface TeacherCredentials {
  reviewToken: string
}

export interface TeacherSession {
  auth_mode: 'review_token_placeholder'
  notice: string
}

export interface TeacherDashboard {
  generated_at: string
  data_notice: string
  metrics: {
    online_devices: number
    offline_devices: number
    never_seen_devices: number
    abnormal_devices: number
    experiment_completion_rate: number | null
  }
  device_status: Array<{
    status: 'online' | 'offline' | 'never_seen' | 'abnormal'
    count: number
  }>
  error_ranking: Array<{ error_code: string; count: number; test_data_only: boolean }>
  error_trend: Array<{ day: string; count: number }>
  class_progress: { configured: boolean; notice: string }
  anomalies: Array<{
    device_id: string
    device_name: string | null
    device_status: 'online' | 'offline' | 'never_seen'
    latest_error_code: string
    latest_summary: string
    evaluated_at: string
    is_test_data: boolean
    student_identity_configured: boolean
  }>
  recent_logs: Array<{
    id: string
    device_id: string
    level: string
    message: string
    event_code: string | null
    occurred_at: string
    is_test_data: boolean
  }>
  interventions: Array<{
    device_id: string
    diagnosis_result_id: string
    tree_title: string
    failure_count: number
    anomaly_duration_seconds: number
    created_at: string
    is_test_data: boolean
    student_identity_configured: boolean
  }>
  knowledge_cases: {
    configured: boolean
    framework_ready: boolean
    source_count: number
    document_count: number
    pending_review_count: number
    approved_chunk_count: number
    embedding_count: number
    embedding_provider_configured: boolean
    notice: string
  }
}
