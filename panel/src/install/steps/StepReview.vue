<script setup lang="ts">
import { computed } from 'vue'
import { NDescriptions, NDescriptionsItem, NTag } from 'naive-ui'

import { useInstallStore } from '../useInstallForm'
import { FIXED_PARAMETERS } from '../fields'

const store = useInstallStore()

const akIdMasked = computed(() => {
  const v = store.credentials.accessKeyId.trim()
  if (!v) return '—'
  if (v.length <= 6) return '******'
  return `${v.slice(0, 3)}****${v.slice(-3)}`
})

const secretMasked = computed(() => (store.credentials.accessKeySecret ? '••••••••••••' : '—'))
</script>

<template>
  <div class="step-review">
    <n-descriptions
      title="访问凭证与地域"
      bordered
      label-placement="left"
      :column="2"
      class="block"
    >
      <n-descriptions-item label="地域 Region">{{ store.region }}</n-descriptions-item>
      <n-descriptions-item label="资源栈名 StackName">{{ store.stackName }}</n-descriptions-item>
      <n-descriptions-item label="AccessKey ID">{{ akIdMasked }}</n-descriptions-item>
      <n-descriptions-item label="AccessKey Secret">{{ secretMasked }}</n-descriptions-item>
    </n-descriptions>

    <n-descriptions title="函数规格" bordered label-placement="left" :column="2" class="block">
      <n-descriptions-item label="CPU">{{ store.spec.Cpu }} vCPU</n-descriptions-item>
      <n-descriptions-item label="内存">{{ store.spec.MemorySize }} MB</n-descriptions-item>
      <n-descriptions-item label="磁盘">{{ store.spec.DiskSize }} MB</n-descriptions-item>
      <n-descriptions-item label="函数超时">{{ store.spec.FunctionTimeout }} 秒</n-descriptions-item>
    </n-descriptions>

    <n-descriptions
      title="固定配置"
      bordered
      label-placement="left"
      :column="2"
      class="block"
    >
      <n-descriptions-item label="函数名">{{ FIXED_PARAMETERS.FunctionName }}</n-descriptions-item>
      <n-descriptions-item label="容器端口">{{ FIXED_PARAMETERS.ContainerPort }}</n-descriptions-item>
      <n-descriptions-item label="镜像地址" :span="2">
        <span class="mono">{{ FIXED_PARAMETERS.ImageUrl }}</span>
      </n-descriptions-item>
      <n-descriptions-item label="资源名前缀">{{ FIXED_PARAMETERS.NamePrefix }}</n-descriptions-item>
      <n-descriptions-item label="可用区">{{ FIXED_PARAMETERS.ZoneId }}</n-descriptions-item>
      <n-descriptions-item label="VPC 网段">{{ FIXED_PARAMETERS.VpcCidrBlock }}</n-descriptions-item>
      <n-descriptions-item label="交换机网段">{{ FIXED_PARAMETERS.VSwitchCidrBlock }}</n-descriptions-item>
      <n-descriptions-item label="EIP 带宽">{{ FIXED_PARAMETERS.EipBandwidth }} Mbps</n-descriptions-item>
      <n-descriptions-item label="EIP 计费">{{ FIXED_PARAMETERS.EipInternetChargeType }}</n-descriptions-item>
      <n-descriptions-item label="触发器">
        {{ FIXED_PARAMETERS.TriggerName }}
        <n-tag size="small" :bordered="false" style="margin-left: 6px">
          {{ FIXED_PARAMETERS.TriggerAuthType }}
        </n-tag>
      </n-descriptions-item>
    </n-descriptions>

    <p class="hint">确认无误后点击「开始部署」，创建过程约 2~5 分钟，请勿关闭页面。</p>
  </div>
</template>

<style scoped>
.step-review {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.block {
  width: 100%;
}
.mono {
  font-family: var(--mono, ui-monospace, Consolas, monospace);
  font-size: 13px;
  word-break: break-all;
}
.hint {
  margin: 0;
  font-size: 13px;
  opacity: 0.7;
}
</style>
