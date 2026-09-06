<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NSpace, NStep, NSteps, NSpin } from 'naive-ui'

import { createInstallStore, resetDeploy } from './useInstallForm'
import { getInstallStatus, type InstallStatus } from '../composables/useInstallState'
import StepPrepare from './steps/StepPrepare.vue'
import StepConfig from './steps/StepConfig.vue'
import StepReview from './steps/StepReview.vue'
import StepDeploy from './steps/StepDeploy.vue'
import StepResult from './steps/StepResult.vue'

const store = createInstallStore()

const STEP_TITLES = ['准备', '填配置', '确认', '部署', '完成'] as const

const current = ref(1)
const deployKey = ref(0)
const configRef = ref<InstanceType<typeof StepConfig> | null>(null)
const router = useRouter()
const loading = ref(true)
const loadError = ref('')
const installation = ref<InstallStatus | null>(null)

async function restore(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const state = await getInstallStatus()
    installation.value = state
    if (state.mode === 'local' || (state.installed && !state.deployment)) {
      await router.replace('/')
      return
    }
    if (state.deployment) {
      const deployment = state.deployment
      store.deploy.stackId = deployment.stackId
      store.deploy.status = deployment.status
      store.deploy.outputs = deployment.outputs ?? null
      store.deploy.phase = state.installed ? 'success' : 'deploying'
      current.value = state.installed ? 5 : 4
      deployKey.value += 1
    } else {
      resetDeploy(store)
      current.value = 1
    }
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '无法获取安装状态'
  } finally {
    loading.value = false
  }
}
onMounted(restore)

const stepsStatus = computed<'process' | 'error' | 'finish'>(() => {
  if (current.value === 4 && store.deploy.phase === 'error') return 'error'
  if (current.value === 5) return 'finish'
  return 'process'
})

const canPrev = computed(() => {
  if (current.value === 2 || current.value === 3) return true
  return false
})

async function next(): Promise<void> {
  if (current.value === 2) {
    const ok = await configRef.value?.validate()
    if (!ok) return
  }
  if (current.value < STEP_TITLES.length) current.value += 1
}

function prev(): void {
  if (current.value === 4) resetDeploy(store)
  if (current.value > 1) current.value -= 1
}

function startDeploy(): void {
  resetDeploy(store)
  deployKey.value += 1
  current.value = 4
}

function retry(): void {
  void restore()
}

function viewResult(): void {
  current.value = 5
}

</script>

<template>
  <div class="wizard-shell">
    <n-card class="wizard-card" :bordered="true">
      <template #header>
        <div class="wizard-title">cloakbrowser 引导安装</div>
      </template>

      <n-steps :current="current" :status="stepsStatus" size="small" class="steps">
        <n-step v-for="title in STEP_TITLES" :key="title" :title="title" />
      </n-steps>

      <n-spin v-if="loading" />
      <n-alert v-else-if="loadError" type="error" title="安装状态查询失败">
        {{ loadError }}
        <n-button @click="restore">重新查询</n-button>
      </n-alert>
      <n-alert v-else-if="installation && !installation.canDeploy && current < 4" type="warning" title="部署前请完成服务器配置">
        {{ installation.missingEnv.join('、') }}
        <n-button @click="restore">重新检查</n-button>
      </n-alert>
      <div v-if="!loading && !loadError" class="step-body">
        <StepPrepare v-if="current === 1" />
        <StepConfig v-else-if="current === 2" ref="configRef" />
        <StepReview v-else-if="current === 3" />
        <StepDeploy v-else-if="current === 4" :key="deployKey" />
        <StepResult v-else-if="current === 5" />
      </div>

      <template #footer>
        <div v-if="!loading && !loadError" class="footer">
          <n-button v-if="canPrev" @click="prev">上一步</n-button>
          <div class="spacer" />
          <n-space>
            <template v-if="current === 1 || current === 2">
              <n-button type="primary" :disabled="!installation?.canDeploy" @click="next">下一步</n-button>
            </template>
            <template v-else-if="current === 3">
              <n-button type="primary" @click="startDeploy">开始部署</n-button>
            </template>
            <template v-else-if="current === 4 && store.deploy.phase === 'error'">
              <n-button type="primary" @click="retry">恢复查询</n-button>
            </template>
            <template v-else-if="current === 4 && store.deploy.phase === 'success'">
              <n-button type="primary" @click="viewResult">查看结果</n-button>
            </template>
            <template v-else-if="current === 5">
              <n-button type="primary" @click="router.push('/')">进入控制台</n-button>
            </template>
          </n-space>
        </div>
      </template>
    </n-card>
  </div>
</template>

<style scoped>
.wizard-shell {
  /* 固定占满整个视口，不依赖父元素高度链；内容超出时内部滚动 */
  position: fixed;
  inset: 0;
  overflow: auto;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 40px 20px;
  box-sizing: border-box;
}
.wizard-card {
  width: 100%;
  max-width: 840px;
}
.wizard-title {
  font-size: 20px;
  font-weight: 600;
}
.steps {
  margin-bottom: 8px;
}
.step-body {
  padding: 24px 4px 8px;
  min-height: 320px;
}
.footer {
  display: flex;
  align-items: center;
  gap: 12px;
}
.spacer {
  flex: 1;
}
</style>
