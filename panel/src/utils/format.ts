/** 展示格式化工具。后端返回 naive-UTC ISO（无时区），按 UTC 解析后转本地展示。 */

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  // 补 Z 视为 UTC；无毫秒也可解析
  const normalized = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false })
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  accepted: '服务端已接收',
  queued: '待执行',
  running: '执行中',
  success: '成功',
  failed: '失败',
  skipped: '已跳过',
  submitted: '页面已显示',
  uncertain: '待核实',
}

export const RUN_STATUS_TYPE: Record<string, 'default' | 'info' | 'success' | 'warning' | 'error'> = {
  accepted: 'info',
  queued: 'default',
  running: 'info',
  success: 'success',
  failed: 'error',
  skipped: 'warning',
  submitted: 'info',
  uncertain: 'warning',
}
