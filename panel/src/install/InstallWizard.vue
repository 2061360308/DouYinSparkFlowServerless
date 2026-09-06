<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NCard, NSpace, NStep, NSteps } from 'naive-ui'

import { createInstallStore, resetDeploy } from './useInstallForm'
import {
  clearInstalled,
  getSavedOutputs,
  isInstalled,
  markInstalled,
} from '../composables/useInstallState'
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

// 已安装（stub）则直接回到「完成」步，展示上次部署输出。
onMounted(() => {
  if (isInstalled()) {
    store.deploy.phase = 'success'
    store.deploy.status = 'CREATE_COMPLETE'
    store.deploy.outputs = getSavedOutputs()
    current.value = 5
  }
})

// 部署成功即持久化安装状态（stub；后端就绪后由接口落库）。
watch(
  () => store.deploy.phase,
  (phase) => {
    if (phase === 'success' && store.deploy.outputs) {
      markInstalled(store.deploy.outputs)
    }
  },
)

const stepsStatus = computed<'process' | 'error' | 'finish'>(() => {
  if (current.value === 4 && store.deploy.phase === 'error') return 'error'
  if (current.value === 5) return 'finish'
  return 'process'
})

const canPrev = computed(() => {
  if (current.value === 2 || current.value === 3) return true
  if (current.value === 4 && store.deploy.phase === 'error') return true
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
  resetDeploy(store)
  deployKey.value += 1
}

function viewResult(): void {
  current.value = 5
}

function reinstall(): void {
  clearInstalled()
  resetDeploy(store)
  current.value = 1
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

      <div class="step-body">
        <StepPrepare v-if="current === 1" />
        <StepConfig v-else-if="current === 2" ref="configRef" />
        <StepReview v-else-if="current === 3" />
        <StepDeploy v-else-if="current === 4" :key="deployKey" />
        <StepResult v-else-if="current === 5" />
      </div>

      <template #footer>
        <div class="footer">
          <n-button v-if="canPrev" @click="prev">上一步</n-button>
          <div class="spacer" />
          <n-space>
            <template v-if="current === 1 || current === 2">
              <n-button type="primary" @click="next">下一步</n-button>
            </template>
            <template v-else-if="current === 3">
              <n-button type="primary" @click="startDeploy">开始部署</n-button>
            </template>
            <template v-else-if="current === 4 && store.deploy.phase === 'error'">
              <n-button type="primary" @click="retry">重试</n-button>
            </template>
            <template v-else-if="current === 4 && store.deploy.phase === 'success'">
              <n-button type="primary" @click="viewResult">查看结果</n-button>
            </template>
            <template v-else-if="current === 5">
              <n-button @click="reinstall">重新安装</n-button>
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
