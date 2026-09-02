import type { UserSession } from '@/types/auth'
import type {
  AIExplanationResponse,
  DeviceCredentials,
  DiagnosisWorkflow,
  StudentDashboard,
  StudentSession,
} from '@/types/student'
import type {
  DiagnosisWorkflowMetrics,
  TeacherDashboard,
  TeacherDiagnosisWorkflow,
} from '@/types/teacher'

export const REVIEW_MODE = import.meta.env.MODE === 'review'

export const reviewStudentCredentials: DeviceCredentials = {
  deviceId: 'review-sht31-01',
  deviceToken: 'review-only-token',
  experimentSessionId: 'review-session-01',
}

export const reviewStudentSession: StudentSession = {
  device_id: reviewStudentCredentials.deviceId,
  display_name: 'SHT31 实验台 01',
  auth_mode: 'device_credential_placeholder',
  student_user_id: 'review-student-01',
  experiment_session_id: reviewStudentCredentials.experimentSessionId ?? null,
  experiment_assignment_id: 'review-assignment-01',
  notice: '前端审核模式：当前内容均为内置合成数据。',
}

const ruleEvidence = {
  fact: '连续读取失败次数',
  observed_value: 3,
  details: [{ event_code: 'I2C_NACK', window_seconds: 30 }],
}

const reviewSensorSamples = [
  ['2026-08-21T05:50:00Z', 24.2, 48.0],
  ['2026-08-21T05:51:00Z', 24.5, 48.6],
  ['2026-08-21T05:52:00Z', 25.0, 49.2],
  ['2026-08-21T05:53:00Z', 25.7, 50.1],
  ['2026-08-21T05:54:00Z', 26.4, 51.0],
  ['2026-08-21T05:55:00Z', 27.1, 52.0],
  ['2026-08-21T05:56:00Z', 27.3, 53.1],
  ['2026-08-21T05:57:00Z', 26.8, 52.7],
  ['2026-08-21T05:58:00Z', 26.3, 52.2],
  ['2026-08-21T05:59:00Z', 26.0, 51.8],
  ['2026-08-21T06:00:00Z', 25.7, 51.2],
] as const

export const reviewStudentDashboard: StudentDashboard = {
  generated_at: '2026-08-21T06:00:00Z',
  task: {
    configured: true,
    title: 'SHT31 温湿度采集与异常排查',
    template_id: 'sht31-i2c-v1',
    notice: '完成传感器接线、连续采样，并根据诊断建议恢复稳定读数。',
  },
  device: {
    device_id: reviewStudentCredentials.deviceId,
    display_name: 'SHT31 实验台 01',
    status: 'online',
    last_seen_at: '2026-08-21T05:59:48Z',
    firmware_version: '1.4.2',
    is_test_fixture: true,
  },
  logs: [
    {
      id: 'review-log-01',
      level: 'INFO',
      message: '展示设备启动完成，传感器初始化成功',
      event_code: 'DEMO_BOOT_OK',
      occurred_at: '2026-08-21T05:50:00Z',
      is_test_data: true,
    },
    {
      id: 'review-log-02',
      level: 'INFO',
      message: '已完成第 4 轮温湿度采样，数据上传正常',
      event_code: 'DEMO_SAMPLE_SYNCED',
      occurred_at: '2026-08-21T05:53:00Z',
      is_test_data: true,
    },
    {
      id: 'review-log-03',
      level: 'WARNING',
      message: '环境温度上升较快，请确认传感器未贴近发热器件',
      event_code: 'DEMO_TEMP_RISING',
      occurred_at: '2026-08-21T05:56:00Z',
      is_test_data: true,
    },
    {
      id: 'review-log-04',
      level: 'INFO',
      message: '温湿度趋势已恢复稳定，展示采样完成',
      event_code: 'DEMO_TREND_STABLE',
      occurred_at: '2026-08-21T06:00:00Z',
      is_test_data: true,
    },
  ],
  readings: reviewSensorSamples.flatMap(([observedAt, temperature, humidity], index) => [
    {
      id: `review-temperature-${index + 1}`,
      sensor_type: 'SHT31',
      metric_key: 'temperature',
      value: temperature,
      unit: '°C',
      observed_at: observedAt,
      is_test_data: true,
    },
    {
      id: `review-humidity-${index + 1}`,
      sensor_type: 'SHT31',
      metric_key: 'humidity',
      value: humidity,
      unit: '%RH',
      observed_at: observedAt,
      is_test_data: true,
    },
  ]),
  diagnosis: {
    id: 'review-diagnosis-01',
    evaluated_at: '2026-08-21T05:59:02Z',
    matches: [
      {
        rule_id: 'sensor.i2c.read_failure',
        error_type: 'I2C_SENSOR_READ_FAILURE',
        priority: 90,
        summary: '传感器连续读取失败，优先检查 I²C 接线与地址配置。',
        evidence: [ruleEvidence],
      },
    ],
    evidence: [{ rule_id: 'sensor.i2c.read_failure', items: [ruleEvidence] }],
    is_test_data: true,
    deterministic_result: {
      diagnosis_result_id: 'review-diagnosis-01',
      primary_error_code: 'SENSOR_READ_FAILED',
      summary: 'SHT31 连续三次未应答，最可能与接线松动或地址配置不一致有关。',
      confidence: 0.86,
      evidence: ['30 秒内连续出现 3 次 I2C_NACK', '温度采样在 05:58 后中断'],
      possible_causes: ['SDA/SCL 接线松动', '传感器地址与代码配置不一致'],
      suggested_steps: ['断电后检查 SDA/SCL 与供电接线', '确认地址扫描结果为 0x44'],
      hint_level: 2,
      need_teacher_help: false,
      rule_ids: ['sensor.i2c.read_failure'],
      knowledge_chunk_ids: ['review-knowledge-01'],
      limitations: ['尚未获得示波器电平数据'],
    },
    explanation: {
      title: 'I²C 传感器读取异常',
      summary: '设备仍在线，但传感器总线连续返回无应答。',
      evidence: ['连续三次 I2C_NACK', '采样曲线出现中断'],
      possible_causes: ['接线松动', '地址配置不一致'],
      steps: ['关闭设备电源', '复核四根连接线', '运行 I²C 地址扫描', '重新开始采样'],
      hint_level: 2,
      need_teacher_help: false,
      limitations: ['无法远程确认物理接线状态'],
      provenance: 'rules_and_reviewed_knowledge',
    },
    ai_enhancement: {
      status: 'disabled',
      trigger_reason: 'review_fixture',
      route: 'rules_only',
      route_path: 'deterministic',
      cache_status: 'not_checked',
    },
  },
  guidance: [
    {
      id: 'review-guidance-01',
      tree_id: 'sht31-i2c-tree',
      tree_title: 'SHT31 无应答排查',
      tree_status: 'matched',
      hint_level: 2,
      failure_count: 3,
      teacher_intervention_required: false,
      ranked_causes: [
        {
          cause_id: 'wiring',
          title: 'SDA / SCL 接线松动或接反',
          score: 0.82,
          confidence: 'high',
          evidence: [{ fact: '连续 NACK', description: '总线没有收到设备应答', weight: 0.8, observed_value: 3, details: [] }],
        },
        {
          cause_id: 'address',
          title: '传感器地址配置不一致',
          score: 0.61,
          confidence: 'medium',
          evidence: [{ fact: '初始化成功后读取失败', description: '地址可能与模块跳线设置不一致', weight: 0.6, observed_value: 1, details: [] }],
        },
      ],
      hints: [
        { cause_id: 'wiring', level: 1, text: '先确认模块供电指示灯是否正常。' },
        { cause_id: 'wiring', level: 2, text: '断电后重新插紧 SDA 与 SCL 连接线。' },
        { cause_id: 'address', level: 3, text: '运行地址扫描并将结果与代码中的 0x44 对照。' },
      ],
      is_test_data: true,
    },
  ],
  feedback: null,
  intervention: null,
  ai_status: {
    framework_ready: true,
    provider_configured: false,
    require_knowledge: true,
    provider: null,
    model: null,
    transport: 'disabled',
    prompt_version: 'review-v1',
    notice: '审核包保持规则诊断模式，不连接外部 AI 服务。',
    ai_enabled: false,
    local_configured: false,
    cloud_configured: false,
    thinking_enabled: false,
    production_route: 'rules_only',
  },
  ai_explanation: null,
  device_state_explanation: {
    status_title: '传感器总线连续无应答',
    status_summary: '主控仍保持在线，但 SHT31 的最近三次读取均未成功。',
    meaning: '程序可以运行，问题更可能位于传感器接线、地址或总线通信层。',
    next_step: '断电后检查 SDA/SCL 接线，再运行 I²C 地址扫描。',
    source: 'rule',
    technical_details: {
      device: { status: 'online', last_seen_at: '2026-08-21T05:59:48Z', firmware_version: '1.4.2' },
      error_code: 'SENSOR_READ_FAILED',
      error_codes: ['I2C_NACK', 'SENSOR_READ_FAILED'],
      retry_count: 3,
      logs: [
        { id: 'review-log-03', level: 'ERROR', message: '连续三次读取失败，已暂停本轮采样', event_code: 'SENSOR_READ_FAILED', occurred_at: '2026-08-21T05:58:42Z' },
      ],
      sensor_readings: [],
      rule_hits: [
        { rule_id: 'sensor.i2c.read_failure', error_type: 'I2C_SENSOR_READ_FAILURE', priority: 90, summary: '传感器连续读取失败', evidence: [ruleEvidence] },
      ],
      fault_tree_evidence: [
        { tree_id: 'sht31-i2c-tree', tree_title: 'SHT31 无应答排查', tree_status: 'matched', hint_level: 2, failure_count: 3, ranked_causes: [] },
      ],
    },
  },
  episode: {
    id: 'review-episode-01',
    status: 'open',
    primary_error_code: 'SENSOR_READ_FAILED',
    started_at: '2026-08-21T05:58:12Z',
    last_seen_at: '2026-08-21T05:59:02Z',
    failure_count: 3,
    current_hint_level: 2,
    ai_call_count: 0,
  },
}

const reviewRuleHit = {
  rule_id: 'sensor.i2c.read_failure',
  error_type: 'I2C_SENSOR_READ_FAILURE',
  summary: 'SHT31 连续三次未应答',
  priority: 90,
  evidence: [{ fact: '连续读取失败次数', observed_value: 3, evidence_refs: ['review-log-02', 'review-log-03'] }],
}

const reviewCandidate = {
  cause_id: 'wiring',
  name: 'SDA / SCL 接线异常',
  score: 0.82,
  evidence_refs: ['review-log-02', 'review-log-03'],
}

const reviewKnowledge = {
  chunk_id: 'review-knowledge-01',
  source_id: 'review-source-01',
  title: 'SHT31 I²C 接线与地址检查清单',
  score: 0.91,
  metadata: { source_type: 'lab_manual', source_version: '1.0', review_status: 'approved' },
}

export const reviewStudentWorkflow: DiagnosisWorkflow = {
  id: 'review-workflow-student-01',
  diagnosis_result_id: 'review-diagnosis-01',
  device_id: reviewStudentCredentials.deviceId,
  graph_thread_id: 'review-thread-student-01',
  graph_version: 'review-v1',
  status: 'completed',
  current_node: null,
  evidence_score: 0.86,
  guidance_level: 2,
  needs_rag: true,
  needs_teacher: false,
  rule_engine_version: 'review-rules-v1',
  fault_tree_version: 'review-tree-v1',
  embedding_version: null,
  model_id: null,
  node_trace: ['collect', 'rules', 'retrieve', 'finalize'],
  final_result: {
    summary: '优先检查 SHT31 的 SDA/SCL 接线与 0x44 地址配置。',
    evidence: ['连续三次读取无应答'],
    possible_causes: ['接线异常', '地址配置不一致'],
    steps: ['断电检查接线', '运行地址扫描', '恢复采样'],
    limitations: ['无法远程确认物理接线'],
    rules_preserved: true,
    rule_hits: [reviewRuleHit],
    knowledge_references: [reviewKnowledge],
    candidate_causes: [reviewCandidate],
    evidence_score: 0.86,
    guidance_level: 2,
    teacher_reviewed: true,
  },
  error_messages: [],
  reviews: [{ id: 'review-review-01', reviewer_user_id: 'review-teacher-01', action: 'approve', comment: '证据充分，建议清晰。', edited_result: null, created_at: '2026-08-21T05:59:40Z' }],
  is_test_data: true,
  created_at: '2026-08-21T05:59:05Z',
  updated_at: '2026-08-21T05:59:40Z',
  completed_at: '2026-08-21T05:59:40Z',
}

export const reviewAIExplanation: AIExplanationResponse = {
  call_record_id: 'review-ai-call-01',
  diagnosis_result_id: 'review-diagnosis-01',
  status: 'succeeded',
  mode: 'ai_enhanced',
  provider_configured: true,
  rules_preserved: true,
  explanation: {
    error_type: 'I2C_SENSOR_READ_FAILURE',
    summary: '设备在线但传感器未应答，请优先排查物理连接。',
    evidence: ['连续三次 I2C_NACK'],
    possible_causes: [{ cause: 'SDA/SCL 接线异常', confidence: 0.82, knowledge_chunk_ids: ['review-knowledge-01'] }],
    steps: ['断电检查接线', '运行地址扫描', '恢复采样'],
    hint_level: 2,
    need_teacher_help: false,
    limitations: ['无法远程观察接线状态'],
  },
  knowledge_references: [],
  notice: '这是审核包中的合成解释，不调用外部模型。',
  enhancement_status: 'local_success',
  trigger_reason: 'review_interaction',
  route: 'review_fixture',
  route_path: 'review_fixture',
  deterministic_result: reviewStudentDashboard.diagnosis?.explanation ?? null,
}

export const reviewTeacherSession: UserSession = {
  access_token: 'review-only-access-token',
  token_type: 'bearer',
  expires_at: '2099-12-31T23:59:59Z',
  user_id: 'review-teacher-01',
  username: 'review-teacher',
  display_name: '王老师 · 审核演示',
  roles: ['teacher'],
  permissions: ['teacher.dashboard.read', 'diagnosis.review'],
  is_test_data: true,
}

export const reviewTeacherDashboard: TeacherDashboard = {
  generated_at: '2026-08-21T06:00:00Z',
  data_notice: '前端审核模式：所有设备、异常和教学介入均为合成展示数据。',
  metrics: { online_devices: 28, offline_devices: 3, never_seen_devices: 1, abnormal_devices: 4, experiment_completion_rate: 0.82 },
  device_status: [
    { status: 'online', count: 28 },
    { status: 'offline', count: 3 },
    { status: 'never_seen', count: 1 },
    { status: 'abnormal', count: 4 },
  ],
  error_ranking: [
    { error_code: 'I2C_NACK', count: 7, test_data_only: true },
    { error_code: 'SENSOR_TIMEOUT', count: 4, test_data_only: true },
    { error_code: 'WIFI_RECONNECT', count: 2, test_data_only: true },
  ],
  error_trend: [
    { day: '2026-08-15', count: 2 }, { day: '2026-08-16', count: 3 },
    { day: '2026-08-17', count: 2 }, { day: '2026-08-18', count: 5 },
    { day: '2026-08-19', count: 4 }, { day: '2026-08-20', count: 6 },
    { day: '2026-08-21', count: 4 },
  ],
  class_progress: { configured: true, notice: '32 名学生中 26 名已完成当前实验，4 名正在排查异常。' },
  anomalies: [
    { device_id: 'review-sht31-01', device_name: 'SHT31 实验台 01', device_status: 'online', latest_error_code: 'I2C_NACK', latest_summary: '传感器连续三次未应答', evaluated_at: '2026-08-21T05:59:02Z', is_test_data: true, student_identity_configured: true },
    { device_id: 'review-esp32-07', device_name: 'ESP32 实验台 07', device_status: 'offline', latest_error_code: 'HEARTBEAT_TIMEOUT', latest_summary: '设备已超过 90 秒未上报心跳', evaluated_at: '2026-08-21T05:57:32Z', is_test_data: true, student_identity_configured: true },
    { device_id: 'review-sht31-12', device_name: 'SHT31 实验台 12', device_status: 'online', latest_error_code: 'TEMP_OUT_OF_RANGE', latest_summary: '温度读数短时超出实验阈值', evaluated_at: '2026-08-21T05:55:18Z', is_test_data: true, student_identity_configured: true },
  ],
  recent_logs: [
    { id: 'teacher-log-01', device_id: 'review-sht31-01', level: 'ERROR', message: '连续三次读取失败，已暂停本轮采样', event_code: 'SENSOR_READ_FAILED', occurred_at: '2026-08-21T05:58:42Z', is_test_data: true },
    { id: 'teacher-log-02', device_id: 'review-esp32-07', level: 'WARNING', message: '超过离线阈值，最后心跳距今 126 秒', event_code: 'HEARTBEAT_TIMEOUT', occurred_at: '2026-08-21T05:57:32Z', is_test_data: true },
    { id: 'teacher-log-03', device_id: 'review-sht31-12', level: 'WARNING', message: '温度读数 42.8°C 超出实验范围', event_code: 'TEMP_OUT_OF_RANGE', occurred_at: '2026-08-21T05:55:18Z', is_test_data: true },
  ],
  interventions: [
    { case_id: 'review-case-01', source: 'student_request', status: 'open', version_no: 1, assigned_teacher_user_id: null, resolution_summary: null, device_id: 'review-sht31-01', diagnosis_result_id: 'review-diagnosis-01', tree_title: 'SHT31 无应答排查', failure_count: 3, anomaly_duration_seconds: 82, created_at: '2026-08-21T05:59:12Z', is_test_data: true, student_identity_configured: true },
    { case_id: 'review-case-02', source: 'automatic_guidance', status: 'recommended', version_no: null, assigned_teacher_user_id: null, resolution_summary: null, device_id: 'review-esp32-07', diagnosis_result_id: 'review-diagnosis-02', tree_title: '设备离线排查', failure_count: 2, anomaly_duration_seconds: 126, created_at: '2026-08-21T05:57:32Z', is_test_data: true, student_identity_configured: true },
  ],
  knowledge_cases: { configured: true, framework_ready: true, source_count: 8, document_count: 24, pending_review_count: 2, approved_chunk_count: 0, case_count: 5, approved_case_count: 3, notice: '已接入并审核结构化实验知识案例。' },
}

const queueWorkflow: TeacherDiagnosisWorkflow = {
  ...reviewStudentWorkflow,
  id: 'review-workflow-queue-01',
  status: 'waiting_teacher',
  needs_teacher: true,
  final_result: null,
  review_request: {
    candidates: [reviewCandidate],
    rule_hits: [reviewRuleHit],
    retrieved_chunks: [reviewKnowledge],
    deterministic_result: { summary: 'SHT31 连续无应答，建议先检查接线与地址。', evidence: ['连续三次 I2C_NACK'], possible_causes: ['接线异常'], steps: ['断电检查接线'], limitations: ['缺少现场接线照片'] },
    instruction: '请确认当前证据是否足以向学生发布排查建议。',
  },
  reviews: [],
  completed_at: null,
}

export const reviewTeacherWorkflowQueue: TeacherDiagnosisWorkflow[] = [queueWorkflow]
export const reviewTeacherWorkflowHistory: TeacherDiagnosisWorkflow[] = [reviewStudentWorkflow]

export const reviewTeacherWorkflowMetrics: DiagnosisWorkflowMetrics = {
  total: 18,
  completed: 13,
  waiting_teacher: 2,
  rejected: 1,
  failed: 0,
  in_progress: 2,
  reviewed: 14,
  edit_rate: 0.14,
  reject_rate: 0.06,
  needs_rag_count: 9,
  resume_count: 3,
  average_node_duration_ms: 184.6,
  ai_call_count: 5,
  ai_input_tokens: 8420,
  ai_output_tokens: 2140,
  ai_estimated_cost: 0.0368,
  student_feedback_count: 12,
  student_resolved_count: 9,
  student_resolution_rate: 0.75,
}
