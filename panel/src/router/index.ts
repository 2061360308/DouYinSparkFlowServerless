/**
 * 应用路由：登录页 + 控制台（受保护，ConsoleLayout 布局）+ 安装向导。
 * 安装向导内部步骤仍是组件内部状态，不作为路由。
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { setUnauthorizedHandler } from '../api/console.http'
import { useAuth } from '../composables/useAuth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/install',
    name: 'install',
    component: () => import('../install/InstallWizard.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../layouts/ConsoleLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
      {
        path: 'change-password',
        name: 'change-password',
        component: () => import('../views/ChangePasswordView.vue'),
        meta: { allowChange: true },
      },
      { path: 'accounts', name: 'accounts', component: () => import('../views/AccountsView.vue') },
      { path: 'scan', name: 'scan', component: () => import('../views/ScanView.vue') },
      { path: 'tasks', name: 'tasks', component: () => import('../views/TasksView.vue') },
      { path: 'runs', name: 'runs', component: () => import('../views/RunsView.vue') },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('../views/admin/AdminUsersView.vue'),
        meta: { requiresAdmin: true },
      },
      {
        path: 'admin/users/:id/quota',
        name: 'admin-user-quota',
        component: () => import('../views/admin/AdminUserQuotaView.vue'),
        meta: { requiresAdmin: true },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

const auth = useAuth()

// 收到 401：清空登录态并跳登录页
setUnauthorizedHandler(() => {
  auth.clear()
  if (router.currentRoute.value.name !== 'login') {
    router.replace({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
  }
})

router.beforeEach(async (to) => {
  if (!auth.state.ready) {
    await auth.refresh()
  }
  const loggedIn = auth.state.user !== null

  // 已登录再访问登录页 → 回首页
  if (to.name === 'login' && loggedIn) {
    return { name: 'dashboard' }
  }
  if (to.meta.public) {
    return true
  }
  if (to.meta.requiresAuth && !loggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  // 强制改密：未改密时只能停留在改密页
  if (loggedIn && auth.state.mustChangePassword && !to.meta.allowChange) {
    return { name: 'change-password' }
  }
  if (to.meta.requiresAdmin && !auth.state.isAdmin) {
    return { name: 'dashboard' }
  }
  return true
})

export default router
