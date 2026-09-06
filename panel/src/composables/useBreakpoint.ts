/**
 * 响应式断点 composable。
 *
 * 基于 window.matchMedia 监听屏幕宽度，返回当前是否处于移动端断点。
 * 主要用于需要 JS 判断的布局（如抽屉菜单、动态列数等）。
 */

import { onMounted, onUnmounted, ref } from 'vue'

const MOBILE_BREAKPOINT = '(max-width: 768px)'

export function useBreakpoint() {
  const isMobile = ref(false)
  let mediaQuery: MediaQueryList | null = null

  function update() {
    isMobile.value = mediaQuery?.matches ?? false
  }

  onMounted(() => {
    if (typeof window === 'undefined') return
    mediaQuery = window.matchMedia(MOBILE_BREAKPOINT)
    update()
    // 兼容旧版 Safari 的 addListener / 现代浏览器的 addEventListener
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', update)
    } else {
      mediaQuery.addListener(update)
    }
  })

  onUnmounted(() => {
    if (!mediaQuery) return
    if (mediaQuery.removeEventListener) {
      mediaQuery.removeEventListener('change', update)
    } else {
      mediaQuery.removeListener(update)
    }
  })

  return { isMobile }
}
