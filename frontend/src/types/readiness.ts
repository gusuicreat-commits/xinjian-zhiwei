export interface ReadinessItem {
  key: string
  label: string
  status: 'ready' | 'blocked' | 'not_required' | 'test_only'
  evidence: string
  required_input: string | null
}

export interface ReadinessStatus {
  overall: 'ready' | 'blocked' | 'test_only'
  version: string
  software_ready: boolean
  demo_ready: boolean
  hardware_ready: boolean
  knowledge_ready: boolean
  organization_ready: boolean
  production_ready: boolean
  items: ReadinessItem[]
}
