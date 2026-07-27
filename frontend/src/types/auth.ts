export interface UserSession {
  access_token: string
  token_type: 'bearer'
  expires_at: string
  user_id: string
  username: string
  display_name: string
  roles: string[]
  permissions: string[]
  is_test_data: boolean
}

export interface CurrentUser {
  id: string
  username: string
  display_name: string
  roles: string[]
  permissions: string[]
  is_test_data: boolean
}

export interface ClassroomSummary {
  id: string
  course_code: string
  course_title: string
  code: string
  name: string
  term: string | null
  access_role: 'student' | 'teacher' | 'admin'
  is_test_data: boolean
}
