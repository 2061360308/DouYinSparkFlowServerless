<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NCollapse,
  NCollapseItem,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  useMessage,
  type FormInst,
  type FormItemRule,
} from 'naive-ui'

import { useInstallStore } from '../useInstallForm'
import {
  CPU_MAX,
  BROWSER_CPU_MIN,
  CPU_MIN,
  CPU_STEP,
  DISK_OPTIONS,
  MEMORY_STEP,
  TASK_MEMORY_FLOOR,
  TIMEOUT_MAX,
  TIMEOUT_MIN,
  clampMemory,
  memoryBounds,
  validateSpec,
} from '../fields'

const store = useInstallStore()
const formRef = ref<FormInst | null>(null)
const message = useMessage()

const diskOptions = DISK_OPTIONS.map((v) => ({ label: `${v} MB`, value: v }))

const memBounds = computed(() => memoryBounds(store.spec.Cpu))
const taskMemBounds = computed(() => memoryBounds(store.spec.TaskCpu, TASK_MEMORY_FLOOR))

const akIdRule: FormItemRule = {
  required: true,
  message: '请输入 AccessKey ID',
  trigger: ['input', 'blur'],
}
const akSecretRule: FormItemRule = {
  required: true,
  message: '请输入 AccessKey Secret',
  trigger: ['input', 'blur'],
}

const cpuRule: FormItemRule = {
  type: 'number',
  required: true,
  trigger: ['change', 'blur'],
  validator(_rule: FormItemRule, value: number | null): true | Error {
    if (value == null || Number.isNaN(value)) return new Error('请输入 CPU')
    if (value < CPU_MIN || value > CPU_MAX) {
      return new Error(`CPU 需在 ${CPU_MIN}~${CPU_MAX} vCPU 之间`)
    }
    return true
  },
}

const memRule = computed<FormItemRule>(() => ({
  type: 'number',
  required: true,
  trigger: ['change', 'blur'],
  validator: (_rule: FormItemRule, value: number | null): true | Error => {
    const { min, max } = memBounds.value
    if (value == null || Number.isNaN(value)) return new Error('请输入内存大小')
    if (value % MEMORY_STEP !== 0) return new Error(`内存需为 ${MEMORY_STEP}MB 的倍数`)
    if (value < min || value > max) {
      return new Error(`内存需在 ${min}~${max} MB 之间（vCPU:GB = 1:1~1:4）`)
    }
    return true
  },
}))

const taskMemRule = computed<FormItemRule>(() => ({
  type: 'number',
  required: true,
  trigger: ['change', 'blur'],
  validator: (_rule: FormItemRule, value: number | null): true | Error => {
    const { min, max } = taskMemBounds.value
    if (value == null || Number.isNaN(value)) return new Error('请输入内存大小')
    if (value % MEMORY_STEP !== 0) return new Error(`内存需为 ${MEMORY_STEP}MB 的倍数`)
    if (value < min || value > max) {
      return new Error(`内存需在 ${min}~${max} MB 之间（vCPU:GB = 1:1~1:4）`)
    }
    return true
  },
}))

// Cpu 变化时，把内存夹取回合法区间，避免比例越界。
watch(
  () => store.spec.Cpu,
  () => {
    store.spec.MemorySize = clampMemory(store.spec.Cpu, store.spec.MemorySize)
  },
)

watch(
  () => store.spec.TaskCpu,
  () => {
    store.spec.TaskMemorySize = clampMemory(
      store.spec.TaskCpu,
      store.spec.TaskMemorySize,
      TASK_MEMORY_FLOOR,
    )
  },
)

async function validate(): Promise<boolean> {
  if (!formRef.value) return false
  try {
    await formRef.value.validate()
  } catch {
    return false
  }
  try {
    validateSpec(store.spec)
    return true
  } catch (error) {
    message.error(error instanceof Error ? error.message : '请检查函数规格')
    return false
  }
}

defineExpose({ validate })
</script>

<template>
  <n-form
    ref="formRef"
    :model="store"
    label-placement="top"
    require-mark-placement="right-hanging"
  >
    <div class="section-title">访问凭证</div>
    <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
      <n-gi span="2 s:1">
        <n-form-item label="AccessKey ID" path="credentials.accessKeyId" :rule="akIdRule">
          <n-input
            v-model:value="store.credentials.accessKeyId"
            placeholder="LTAI..."
            clearable
          />
        </n-form-item>
      </n-gi>
      <n-gi span="2 s:1">
        <n-form-item
          label="AccessKey Secret"
          path="credentials.accessKeySecret"
          :rule="akSecretRule"
        >
          <n-input
            v-model:value="store.credentials.accessKeySecret"
            type="password"
            show-password-on="click"
            placeholder="请输入 AccessKey Secret"
            clearable
          />
        </n-form-item>
      </n-gi>
    </n-grid>

    <div class="section-title">地域与资源栈</div>
    <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
      <n-gi span="2 s:1">
        <n-form-item label="地域 Region">
          <n-input :value="store.region" readonly />
        </n-form-item>
      </n-gi>
      <n-gi span="2 s:1">
        <n-form-item label="资源栈名 StackName">
          <n-input :value="store.stackName" readonly />
        </n-form-item>
      </n-gi>
    </n-grid>

    <n-collapse class="advanced">
      <n-collapse-item title="高级：浏览器函数规格" name="spec">
        <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
          <n-gi span="2 s:1">
            <n-form-item label="CPU（vCPU）" path="spec.Cpu" :rule="cpuRule">
              <n-input-number
                v-model:value="store.spec.Cpu"
                :min="BROWSER_CPU_MIN"
                :max="CPU_MAX"
                :step="CPU_STEP"
                :precision="2"
                class="fill"
              />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="内存（MB）" path="spec.MemorySize" :rule="memRule">
              <n-input-number
                v-model:value="store.spec.MemorySize"
                :min="memBounds.min"
                :max="memBounds.max"
                :step="MEMORY_STEP"
                :precision="0"
                class="fill"
              />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="磁盘（MB）" path="spec.DiskSize">
              <n-select v-model:value="store.spec.DiskSize" :options="diskOptions" />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="函数超时（秒）" path="spec.FunctionTimeout">
              <n-input-number
                v-model:value="store.spec.FunctionTimeout"
                :min="TIMEOUT_MIN"
                :max="TIMEOUT_MAX"
                :step="1"
                :precision="0"
                class="fill"
              />
            </n-form-item>
          </n-gi>
        </n-grid>
        <p class="hint">
          当前 CPU 下内存可选范围：{{ memBounds.min }}~{{ memBounds.max }} MB（64MB 倍数，
          vCPU:GB = 1:1~1:4）。会话亲和、健康检查、镜像、触发器等其余参数均采用固定默认值。
        </p>
      </n-collapse-item>

      <n-collapse-item title="高级：任务执行器函数规格" name="task-spec">
        <n-grid :cols="2" :x-gap="16" responsive="screen" item-responsive>
          <n-gi span="2 s:1">
            <n-form-item label="CPU（vCPU）" path="spec.TaskCpu" :rule="cpuRule">
              <n-input-number
                v-model:value="store.spec.TaskCpu"
                :min="CPU_MIN"
                :max="CPU_MAX"
                :step="CPU_STEP"
                :precision="2"
                class="fill"
              />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="内存（MB）" path="spec.TaskMemorySize" :rule="taskMemRule">
              <n-input-number
                v-model:value="store.spec.TaskMemorySize"
                :min="taskMemBounds.min"
                :max="taskMemBounds.max"
                :step="MEMORY_STEP"
                :precision="0"
                class="fill"
              />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="磁盘（MB）">
              <n-input value="512" readonly />
            </n-form-item>
          </n-gi>
          <n-gi span="2 s:1">
            <n-form-item label="函数超时（秒）" path="spec.TaskFunctionTimeout">
              <n-input-number
                v-model:value="store.spec.TaskFunctionTimeout"
                :min="TIMEOUT_MIN"
                :max="TIMEOUT_MAX"
                :step="1"
                :precision="0"
                class="fill"
              />
            </n-form-item>
          </n-gi>
        </n-grid>
        <p class="hint">
          当前 CPU 下内存可选范围：{{ taskMemBounds.min }}~{{ taskMemBounds.max }} MB（64MB
          倍数）。任务执行器磁盘固定 512MB，其余参数均采用固定默认值。
        </p>
      </n-collapse-item>
    </n-collapse>
  </n-form>
</template>

<style scoped>
.section-title {
  font-weight: 600;
  margin: 4px 0 12px;
  opacity: 0.85;
}
.advanced {
  margin-top: 8px;
}
.fill {
  width: 100%;
}
.hint {
  margin: 8px 0 0;
  font-size: 13px;
  opacity: 0.65;
  line-height: 1.6;
}
</style>
