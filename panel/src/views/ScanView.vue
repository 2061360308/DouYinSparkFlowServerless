<script setup lang="ts">
import { NAlert, NButton, NCard, NIcon, NResult } from 'naive-ui'
import { QrCodeOutline } from '@vicons/ionicons5'
</script>

<template>
  <n-card>
    <n-result status="info" title="扫码登录">
      <template #icon>
        <n-icon :size="60" :component="QrCodeOutline" color="#aa3bff" />
      </template>
      <template #default>
        <p class="lead">通过抖音 App 扫码，安全地绑定账号登录凭证，无需手动导出 Cookie。</p>
        <n-alert type="warning" :bordered="true" title="功能筹备中" class="tip">
          扫码登录依赖常驻的浏览器自动化执行环境，本期尚未部署（控制台已就绪）。
          可先在「抖音账号」中通过 Cookie JSON 手动添加账号。
        </n-alert>
      </template>
      <template #footer>
        <n-button disabled>开始扫码（即将上线）</n-button>
      </template>
    </n-result>
  </n-card>
</template>

<style scoped>
.lead {
  max-width: 520px;
  margin: 0 auto 16px;
  opacity: 0.75;
}
.tip {
  max-width: 560px;
  margin: 0 auto;
  text-align: left;
}
</style>
