<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { NAlert, NProgress, NSpin } from 'naive-ui'

import { useInstallStore } from '../useInstallForm'
import { buildParameters } from '../fields'
import { TOTAL_RESOURCE_STAGES, deployStack, getDeployStatus } from '../../api/install'

const store = useInstallStore()

let timer: ReturnType<typeof setInterval> | null = null

const percentage = computed(() => {
  if (store.deploy.phase === 'success') return 100
  const n = store.deploy.events.length
  return Math.min(99, Math.round((n / TOTAL_RESOURCE_STAGES) * 100))
})

const progressStatus = computed<'default' | 'success' | 'error'>(() => {
  if (store.deploy.phase === 'success') return 'success'
  if (store.deploy.phase === 'error') return 'error'
  return 'default'
})

function stopPolling(): void {
  if (timer !== null) {
    clearInterval(timer)
    timer = null
  }
}

async function poll(): Promise<void> {
  try {
    const status = await getDeployStatus(store.deploy.stackId)
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
    store.deploy.error = err instanceof Error ? err.message : String(err)
    store.deploy.phase = 'error'
    stopPolling()
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
    store.deploy.stackId = handle.stackId
    await poll()
    if (store.deploy.phase === 'deploying') {
      timer = setInterval(poll, 1000)
    }
  } catch (err) {
    store.deploy.error = err instanceof Error ? err.message : String(err)
    store.deploy.phase = 'error'
  }
}

onMounted(() => {
  if (store.deploy.phase === 'idle') {
    void run()
  }
})

onUnmounted(stopPolling)
</script>

<template>
  <div class="step-deploy">
    <div class="head">
      <n-spin v-if="store.deploy.phase === 'deploying'" :size="20" />
      <span class="title">
        <template v-if="store.deploy.phase === 'deploying'">正在创建资源栈…</template>
        <template v-else-if="store.deploy.phase === 'success'">资源栈创建完成</template>
        <template v-else-if="store.deploy.phase === 'error'">资源栈创建失败</template>
        <template v-else>准备部署…</template>
      </span>
    </div>

    <n-progress
      type="line"
      :percentage="percentage"
      :status="progressStatus"
      :processing="store.deploy.phase === 'deploying'"
      :indicator-placement="'inside'"
    />

    <div v-if="store.deploy.stackId" class="stack-id">
      资源栈 ID：<span class="mono">{{ store.deploy.stackId }}</span>
    </div>

    <div class="events" role="log" aria-live="polite">
      <div v-if="store.deploy.events.length === 0" class="event empty">等待资源开始创建…</div>
      <div v-for="ev in store.deploy.events" :key="ev.logicalResourceId" class="event">
        <span class="ok">✓</span>
        <span class="res">{{ ev.logicalResourceId }}</span>
        <span class="type">{{ ev.resourceType }}</span>
      </div>
    </div>

    <n-alert v-if="store.deploy.phase === 'error'" type="error" title="部署失败">
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
