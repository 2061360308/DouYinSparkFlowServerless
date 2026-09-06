<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { NAlert, NSpin } from 'naive-ui'

import { useInstallStore } from '../useInstallForm'
import { buildParameters } from '../fields'
import { deployStack, getDeployStatus } from '../../api/install'

const store = useInstallStore()

let timer: ReturnType<typeof setTimeout> | null = null
let active = true

function stopPolling(): void {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

async function poll(): Promise<void> {
  if (!active) return
  try {
    const status = await getDeployStatus(store.deploy.stackId)
    if (!active) return
    store.deploy.status = status.status
    store.deploy.events = status.events
    store.deploy.statusReason = status.statusReason ?? ''
    if (status.status === 'CREATE_COMPLETE') {
      store.deploy.outputs = status.outputs ?? null
      store.deploy.phase = 'success'
      stopPolling()
    } else if (status.status === 'CREATE_FAILED') {
      store.deploy.error = status.statusReason || '资源栈创建失败'
      store.deploy.phase = 'error'
      stopPolling()
    }
  } catch (err) {
    if (!active) return
    store.deploy.error = err instanceof Error ? err.message : String(err)
    store.deploy.phase = 'error'
    stopPolling()
  }
  if (active && store.deploy.phase === 'deploying') {
    timer = setTimeout(() => { void poll() }, 5000)
  }
}

async function run(): Promise<void> {
  store.deploy.phase = 'deploying'
  store.deploy.error = ''
  try {
    const handle = await deployStack({
      region: store.region,
      stackName: store.stackName,
      credentials: { ...store.credentials },
      parameters: buildParameters(store.spec),
    })
    if (!active) return
    store.deploy.stackId = handle.stackId
    await poll()
  } catch (err) {
    if (!active) return
    store.deploy.error = err instanceof Error ? err.message : String(err)
    store.deploy.phase = 'error'
  }
}

onMounted(() => {
  if (store.deploy.phase === 'idle') {
    void run()
  } else if (store.deploy.phase === 'deploying') {
    void poll()
  }
})

onUnmounted(() => {
  active = false
  stopPolling()
})
</script>

<template>
  <div class="step-deploy">
    <div class="head">
      <n-spin v-if="store.deploy.phase === 'deploying'" :size="20" />
      <span class="title">
        <template v-if="store.deploy.phase === 'deploying'">正在创建资源栈…</template>
        <template v-else-if="store.deploy.phase === 'success'">资源栈创建完成</template>
        <template v-else-if="store.deploy.phase === 'error'">部署需要处理</template>
        <template v-else>准备部署…</template>
      </span>
    </div>

    <div v-if="store.deploy.stackId" class="stack-id">
      资源栈 ID：<span class="mono">{{ store.deploy.stackId }}</span>
    </div>

    <div class="events" role="log" aria-live="polite">
      <div v-if="store.deploy.events.length === 0" class="event empty">资源栈状态：{{ store.deploy.status || '提交中' }}。创建可能需要数分钟，可刷新页面恢复查询。</div>
      <div v-for="ev in store.deploy.events" :key="ev.logicalResourceId" class="event">
        <span class="ok">✓</span>
        <span class="res">{{ ev.logicalResourceId }}</span>
        <span class="type">{{ ev.resourceType }}</span>
      </div>
    </div>

    <n-alert v-if="store.deploy.phase === 'error'" type="error" title="部署或状态查询未完成">
      {{ store.deploy.error }}
    </n-alert>
  </div>
</template>

<style scoped>
.step-deploy {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.title {
  font-weight: 600;
  font-size: 16px;
}
.stack-id {
  font-size: 13px;
  opacity: 0.75;
}
.mono {
  font-family: var(--mono, ui-monospace, Consolas, monospace);
}
.events {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.24));
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 220px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.event {
  display: flex;
  align-items: center;
  gap: 10px;
}
.event.empty {
  opacity: 0.6;
}
.ok {
  color: #18a058;
  font-weight: 700;
}
.res {
  font-weight: 600;
  min-width: 130px;
}
.type {
  opacity: 0.6;
  font-family: var(--mono, ui-monospace, Consolas, monospace);
}
</style>
