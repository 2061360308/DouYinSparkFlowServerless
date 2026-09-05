/**
 * 应用路由。
 *
 * 顶层页面走路由；安装向导内部 5 个步骤仍是组件内部状态，不作为路由。
 * 本期仅有 /install 一个实义路由；守卫按"是否已安装"预置了受保护路由分支
 * （meta.requiresInstall），待后端与安装后落地页（如 /dashboard）就绪后启用。
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { isInstalled } from '../composables/useInstallState'

const routes: RouteRecordRaw[] = [
  {
    path: '/install',
    name: 'install',
    // 懒加载：把 naive-ui + 向导拆为独立 chunk，减小首屏 JS。
    component: () => import('../install/InstallWizard.vue'),
  },
  {
    path: '/',
    redirect: '/install',
  },
  {
    // 兜底：未知路径回到安装向导。
    path: '/:pathMatch(.*)*',
    redirect: '/install',
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 安装门控（stub）：受保护路由在未安装时回退到 /install。
// 目前无受保护路由；后端就绪后，将 isInstalled() 换成真实接口判定即可。
router.beforeEach((to) => {
  if (to.meta.requiresInstall && !isInstalled()) {
    return { name: 'install' }
  }
  return true
})

export default router
