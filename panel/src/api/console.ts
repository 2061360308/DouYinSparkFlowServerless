/** 控制台后端 API（类型 + 调用封装）。 */

import { http } from './console.http'

export interface UserInfo {
  id: string
  username: string
  role: string
}

export interface MeResponse {
  user: UserInfo
  csrf_token: string
  is_admin: boolean
  must_change_password: boolean
}

export interface LoginResponse {
  csrf_token: string
  must_change_password: boolean
  user: UserInfo
}

export interface AccountItem {
  id: string
  display_name: string
  validation_state: string
}

export interface ConversationItem {
  name: string
  sec_uid: string | null
}

export interface QuotaGrant {
  id: string
  amount: number
  label: string
  starts_at: string
  expires_at: string | null
  status: string
  days_remaining: number | null
}

export interface QuotaSummary {
  limit: number | null
  active_usage: number
  saved_usage: number
  max_saved_tasks: number
  grants: QuotaGrant[]
}

export interface TaskItem {
  id: string
  account_id: string | null
  target_name: string
  target_sec_uid: string
  send_time: string
  message_template: string
  enabled: boolean
  next_run_at: string | null
}

export interface Availability {
  available: boolean
  remaining: number
  suggestions: string[]
}

export interface RunItem {
  id: string
  task_id: string
  target_name: string | null
  send_time: string | null
  scheduled_for: string | null
  status: string
  stage: string
  started_at: string | null
  finished_at: string | null
  error_code: string | null
  error_summary: string | null
  owner_username?: string
}

export interface Pagination {
  page: number
  pages: number
  total: number
  has_previous: boolean
  has_next: boolean
}

export interface PlatformStatus {
  total: number
  success: number
  running: number
  pending: number
  failed: number
  worker_online: boolean
  updated_at: string
}

export interface DashboardData {
  tasks: Array<{ id: string; target_name: string; send_time: string; enabled: boolean; next_run_at: string | null }>
  accounts: AccountItem[]
  recent_runs: Array<{ id: string; target_name: string | null; scheduled_for: string | null; status: string; stage: string }>
  platform_status: PlatformStatus
}

export interface AdminUserRow {
  id: string
  username: string
  role: string
  status: string
  must_change_password: boolean
  created_at: string | null
  quota: QuotaSummary
}

export interface QuotaPolicy {
  default_amount: number
  default_duration_days: number | null
  max_saved_tasks: number
}

export interface TaskBody {
  account_id: string
  target_name: string
  target_sec_uid?: string
  send_time: string
  message_template: string
}

export const authApi = {
  me: () => http.get<MeResponse>('/api/auth/me', true),
  login: (username: string, password: string) =>
    http.post<LoginResponse>('/api/auth/login', { username, password }),
  logout: () => http.post<{ ok: boolean }>('/api/auth/logout'),
  changePassword: (current_password: string, new_password: string, new_password_confirmation: string) =>
    http.post<{ ok: boolean }>('/api/auth/change-password', {
      current_password,
      new_password,
      new_password_confirmation,
    }),
}

export const accountApi = {
  list: () => http.get<{ items: AccountItem[] }>('/api/accounts'),
  create: (display_name: string, cookies: string) =>
    http.post<{ id: string; display_name: string }>('/api/accounts', { display_name, cookies }),
  remove: (id: string) => http.del<{ ok: boolean }>(`/api/accounts/${id}`),
  conversations: (id: string) => http.get<{ items: ConversationItem[] }>(`/api/accounts/${id}/conversations`),
}

export const taskApi = {
  list: () => http.get<{ items: TaskItem[]; quota: QuotaSummary }>('/api/tasks'),
  get: (id: string) => http.get<TaskItem>(`/api/tasks/${id}`),
  create: (body: TaskBody) => http.post<TaskItem>('/api/tasks', body),
  update: (id: string, body: TaskBody) => http.put<TaskItem>(`/api/tasks/${id}`, body),
  toggle: (id: string) => http.post<TaskItem>(`/api/tasks/${id}/toggle`),
  remove: (id: string) => http.del<{ ok: boolean }>(`/api/tasks/${id}`),
  availability: (send_time: string, exclude_task_id = '') =>
    http.get<Availability>(
      `/api/tasks/availability?send_time=${encodeURIComponent(send_time)}` +
        (exclude_task_id ? `&exclude_task_id=${encodeURIComponent(exclude_task_id)}` : ''),
    ),
}

export const runApi = {
  list: (page = 1) =>
    http.get<{ items: RunItem[]; page: Pagination; show_owner: boolean }>(`/api/runs?page=${page}`),
}

export const dashboardApi = {
  get: () => http.get<DashboardData>('/api/dashboard'),
  platformStatus: () => http.get<PlatformStatus>('/api/platform-status'),
}

export interface SystemConfigMap {
  values: Record<string, string>
}

export const adminApi = {
  users: (q = '', page = 1) =>
    http.get<{ items: AdminUserRow[]; page: Pagination }>(
      `/api/admin/users?q=${encodeURIComponent(q)}&page=${page}`,
    ),
  createUser: (username: string) =>
    http.post<{ temporary_password: string }>('/api/admin/users', { username }),
  toggleUser: (id: string) => http.post<{ ok: boolean }>(`/api/admin/users/${id}/toggle`),
  resetPassword: (id: string) =>
    http.post<{ temporary_password: string }>(`/api/admin/users/${id}/reset-password`),
  deleteUser: (id: string, confirmation: string) =>
    http.del<{ ok: boolean }>(`/api/admin/users/${id}`, { confirmation }),
  quotaPolicy: () => http.get<QuotaPolicy>('/api/admin/quota-policy'),
  updateQuotaPolicy: (body: QuotaPolicy) => http.put<{ ok: boolean }>('/api/admin/quota-policy', body),
  userQuota: (id: string) =>
    http.get<{ user: AdminUserRow; quota: QuotaSummary }>(`/api/admin/users/${id}/quota`),
  addGrant: (id: string, body: { amount: number; starts_at: string; expires_at?: string; label: string }) =>
    http.post<{ ok: boolean }>(`/api/admin/users/${id}/quota-grants`, body),
  revokeGrant: (grantId: string) =>
    http.post<{ ok: boolean }>(`/api/admin/quota-grants/${grantId}/revoke`),
  setTaskLimit: (id: string, task_limit: number) =>
    http.post<{ ok: boolean }>(`/api/admin/users/${id}/task-limit`, { task_limit }),
  getSystemConfig: () => http.get<SystemConfigMap>('/api/admin/system-config'),
  updateSystemConfig: (values: Record<string, string>) =>
    http.put<{ ok: boolean }>('/api/admin/system-config', { values }),
}
