/**
 * 安装状态（stub）。
 *
 * 本期用 localStorage 暂存"是否已安装"及最近一次部署输出，供路由守卫与向导
 * 恢复"已完成"状态使用。后端就绪后，应替换为对真实接口的调用
 * （例如 GET /api/install/status ↔ RosStackClient.get_stack_status/outputs），
 * 保持下列函数签名不变即可平滑切换。
 */

import type { StackOutputs } from '../api/install'

const INSTALLED_KEY = 'panel.installed'
const OUTPUTS_KEY = 'panel.install.outputs'

/** 是否已完成安装。 */
export function isInstalled(): boolean {
  try {
    return localStorage.getItem(INSTALLED_KEY) === '1'
  } catch {
    return false
  }
}

/** 标记安装完成，并保存部署输出。 */
export function markInstalled(outputs: StackOutputs | null): void {
  try {
    localStorage.setItem(INSTALLED_KEY, '1')
    if (outputs) {
      localStorage.setItem(OUTPUTS_KEY, JSON.stringify(outputs))
    }
  } catch {
    /* localStorage 不可用时静默忽略（不阻断流程） */
  }
}

/** 清除安装状态（用于"重新安装"）。 */
export function clearInstalled(): void {
  try {
    localStorage.removeItem(INSTALLED_KEY)
    localStorage.removeItem(OUTPUTS_KEY)
  } catch {
    /* 忽略 */
  }
}

/** 读取上次保存的部署输出（无则返回 null）。 */
export function getSavedOutputs(): StackOutputs | null {
  try {
    const raw = localStorage.getItem(OUTPUTS_KEY)
    if (!raw) return null
    return JSON.parse(raw) as StackOutputs
  } catch {
    return null
  }
}
