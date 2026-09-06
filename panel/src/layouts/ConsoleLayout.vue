<script setup lang="ts">
import { computed, h, onMounted, ref, type Component } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import {
  NAvatar,
  NButton,
  NDrawer,
  NDropdown,
  NIcon,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NText,
  useMessage,
  type MenuOption,
} from 'naive-ui'
import {
  FlameOutline,
  GridOutline,
  KeyOutline,
  LogOutOutline,
  MenuOutline,
  PeopleOutline,
  PersonCircleOutline,
  QrCodeOutline,
  ReceiptOutline,
  SettingsOutline,
} from '@vicons/ionicons5'

import { useAuth } from '../composables/useAuth'
import { useBreakpoint } from '../composables/useBreakpoint'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { state, logout } = useAuth()
const { isMobile } = useBreakpoint()

const collapsed = ref(false)
const drawerVisible = ref(false)

function renderIcon(icon: Component) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = computed<MenuOption[]>(() => {
  const base: MenuOption[] = [
    { label: '仪表盘', key: 'dashboard', icon: renderIcon(GridOutline) },
    { label: '抖音账号', key: 'accounts', icon: renderIcon(PersonCircleOutline) },
    { label: '扫码登录', key: 'scan', icon: renderIcon(QrCodeOutline) },
    { label: '续火任务', key: 'tasks', icon: renderIcon(FlameOutline) },
    { label: '执行记录', key: 'runs', icon: renderIcon(ReceiptOutline) },
  ]
  if (state.isAdmin) {
    base.push({ label: '用户管理', key: 'admin-users', icon: renderIcon(PeopleOutline) })
    base.push({ label: '系统设置', key: 'admin-system-settings', icon: renderIcon(SettingsOutline) })
  }
  return base
})

const activeKey = computed(() => {
  const name = route.name?.toString() ?? ''
  if (name === 'admin-user-quota') return 'admin-users'
  return name
})

const TITLES: Record<string, string> = {
  dashboard: '仪表盘',
  accounts: '抖音账号',
  scan: '扫码登录',
  tasks: '续火任务',
  runs: '执行记录',
  'admin-users': '用户管理',
  'admin-user-quota': '任务额度',
  'admin-system-settings': '系统设置',
  'change-password': '修改密码',
}
const pageTitle = computed(() => TITLES[route.name?.toString() ?? ''] ?? 'DouyinSpark 控制台')

function onMenu(key: string) {
  drawerVisible.value = false
  router.push({ name: key })
}

function openDrawer() {
  drawerVisible.value = true
}

const userOptions = [
  { label: '修改密码', key: 'change-password', icon: renderIcon(KeyOutline) },
  { label: '退出登录', key: 'logout', icon: renderIcon(LogOutOutline) },
]

async function onUserSelect(key: string) {
  if (key === 'change-password') {
    router.push({ name: 'change-password' })
  } else if (key === 'logout') {
    await logout()
    message.success('已退出登录')
    router.replace({ name: 'login' })
  }
}

onMounted(() => {
  // 平台状态每分钟兜底刷新一次由各页面自行处理
})
</script>

<template>
  <n-layout has-sider class="shell">
    <!-- 桌面端固定侧边栏 -->
    <n-layout-sider
      v-if="!isMobile"
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="220"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
    >
      <div class="brand">
        <n-icon :size="22" :component="FlameOutline" class="brand-icon" />
        <span v-if="!collapsed" class="brand-text">DouyinSpark</span>
      </div>
      <n-menu
        :value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :options="menuOptions"
        @update:value="onMenu"
      />
    </n-layout-sider>

    <n-layout>
      <n-layout-header bordered class="header">
        <div class="header-left">
          <n-button v-if="isMobile" quaternary class="menu-btn" @click="openDrawer">
            <template #icon>
              <n-icon :size="22" :component="MenuOutline" />
            </template>
          </n-button>
          <div class="title">{{ pageTitle }}</div>
        </div>
        <n-dropdown trigger="click" :options="userOptions" @select="onUserSelect">
          <n-button quaternary class="user-btn">
            <template #icon>
              <n-avatar round :size="26" color="#aa3bff">
                {{ (state.user?.username ?? '?').slice(0, 1).toUpperCase() }}
              </n-avatar>
            </template>
            <span v-if="!isMobile" class="user-name">{{ state.user?.username }}</span>
            <n-text v-if="!isMobile && state.isAdmin" depth="3" class="role-tag">管理员</n-text>
          </n-button>
        </n-dropdown>
      </n-layout-header>

      <n-layout-content class="content">
        <div class="content-inner">
          <router-view />
        </div>
      </n-layout-content>
    </n-layout>

    <!-- 移动端抽屉菜单 -->
    <n-drawer
      v-model:show="drawerVisible"
      :width="240"
      placement="left"
      :auto-focus="false"
      class="drawer-menu"
    >
      <div class="drawer-brand">
        <n-icon :size="22" :component="FlameOutline" class="brand-icon" />
        <span class="brand-text">DouyinSpark</span>
      </div>
      <n-menu
        :value="activeKey"
        :collapsed="false"
        :collapsed-width="64"
        :options="menuOptions"
        @update:value="onMenu"
      />
    </n-drawer>
  </n-layout>
</template>

<style scoped>
.shell {
  /* 固定占满整个视口，不依赖父元素高度链，避免地址栏变化导致抖动 */
  position: fixed;
  inset: 0;
}
.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  font-weight: 700;
  font-size: 17px;
  color: var(--n-text-color, #333);
}
.drawer-brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  font-weight: 700;
  font-size: 17px;
  color: var(--n-text-color, #333);
  border-bottom: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.24));
}
.brand-icon {
  color: #aa3bff;
}
.brand-text {
  letter-spacing: 0.3px;
}
.header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.menu-btn {
  padding: 0 6px;
}
.title {
  font-size: 16px;
  font-weight: 600;
}
.user-btn {
  display: flex;
  align-items: center;
  gap: 8px;
}
.user-name {
  font-weight: 500;
}
.role-tag {
  font-size: 12px;
}
.content {
  height: calc(100% - 56px);
  overflow: auto;
  background: rgba(128, 128, 128, 0.05);
}
.content-inner {
  max-width: 1080px;
  margin: 0 auto;
  padding: 24px 20px 40px;
}
@media (max-width: 768px) {
  .content-inner {
    padding: 16px 12px 24px;
  }
}
</style>
