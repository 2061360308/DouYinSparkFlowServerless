/** 全局登录态（模块级单例，沿用 panel 的轻量 composable 风格，不引 Pinia）。 */

import { reactive } from 'vue'

import { authApi, type UserInfo } from '../api/console'
import { csrfToken } from '../api/console.http'

interface AuthState {
  user: UserInfo | null
  isAdmin: boolean
  mustChangePassword: boolean
  ready: boolean
}

const state = reactive<AuthState>({
  user: null,
  isAdmin: false,
  mustChangePassword: false,
  ready: false,
})

function applyMe(me: { user: UserInfo; csrf_token: string; is_admin: boolean; must_change_password: boolean }): void {
  state.user = me.user
  state.isAdmin = me.is_admin
  state.mustChangePassword = me.must_change_password
  csrfToken.value = me.csrf_token
}

function clear(): void {
  state.user = null
  state.isAdmin = false
  state.mustChangePassword = false
  csrfToken.value = ''
}

async function refresh(): Promise<void> {
  try {
    applyMe(await authApi.me())
  } catch {
    clear()
  } finally {
    state.ready = true
  }
}

async function login(username: string, password: string): Promise<void> {
  const res = await authApi.login(username, password)
  state.user = res.user
  state.isAdmin = res.user.role === 'admin'
  state.mustChangePassword = res.must_change_password
  csrfToken.value = res.csrf_token
  state.ready = true
}

async function logout(): Promise<void> {
  try {
    await authApi.logout()
  } finally {
    clear()
  }
}

export function useAuth() {
  return { state, refresh, login, logout, clear }
}
