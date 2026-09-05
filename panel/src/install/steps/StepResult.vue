<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NResult, useMessage } from 'naive-ui'

import { useInstallStore } from '../useInstallForm'

const store = useInstallStore()
const message = useMessage()

const outputs = computed(() => store.deploy.outputs)

const rows = computed(() => {
  const o = store.deploy.outputs
  if (!o) return [] as Array<{ label: string; value: string; hint?: string }>
  const list: Array<{ label: string; value: string; hint?: string }> = []
  if (o.EipIpAddress) {
    list.push({
      label: '固定公网出口 IP',
      value: o.EipIpAddress,
      hint: '对外呈现的固定出口地址（EIP）',
    })
  }
  if (o.TriggerUrlInternet) {
    list.push({ label: 'Web 触发器公网地址', value: o.TriggerUrlInternet })
  }
  if (o.FunctionName) {
    list.push({ label: '函数名称', value: o.FunctionName })
  }
  return list
})

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    message.success('已复制')
  } catch {
    message.error('复制失败，请手动选择复制')
  }
}
</script>

<template>
  <n-result
    status="success"
    title="安装完成"
    description="资源栈已创建成功，以下为部署输出。"
  >
    <template #footer>
      <div v-if="outputs" class="outputs">
        <div v-for="row in rows" :key="row.label" class="row">
          <div class="meta">
            <span class="label">{{ row.label }}</span>
            <span v-if="row.hint" class="hint">{{ row.hint }}</span>
          </div>
          <div class="value">
            <span class="text">{{ row.value }}</span>
            <n-button size="tiny" tertiary @click="copy(row.value)">复制</n-button>
          </div>
        </div>
      </div>
      <p v-else class="empty">未获取到部署输出。</p>
    </template>
  </n-result>
</template>

<style scoped>
.outputs {
  display: flex;
  flex-direction: column;
  gap: 10px;
  text-align: left;
  max-width: 640px;
  margin: 0 auto;
}
.row {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.24));
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.label {
  font-weight: 600;
}
.hint {
  font-size: 12px;
  opacity: 0.6;
}
.value {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.text {
  font-family: var(--mono, ui-monospace, Consolas, monospace);
  font-size: 13px;
  word-break: break-all;
  text-align: right;
}
.empty {
  opacity: 0.7;
}
</style>
