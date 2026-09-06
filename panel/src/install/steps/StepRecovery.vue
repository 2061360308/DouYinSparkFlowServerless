<script setup lang="ts">
import { computed, ref } from 'vue'
import { NAlert, NButton, NFormItem, NInput, NSpace, useMessage } from 'naive-ui'
import { cleanupInstallation, repairInstallCredentials, resetInstallation } from '../../api/install'
import { useInstallStore } from '../useInstallForm'
const emit = defineEmits<{ restored: [] }>()
const store = useInstallStore()
const message = useMessage()
const confirmation = ref('')
const credentials = ref({ accessKeyId: '', accessKeySecret: '' })
const busy = ref(false)
const error = ref('')
const expected = computed(() => store.deploy.stackId || 'DouyinSpark')
const confirmed = computed(() => confirmation.value === expected.value)
const deleted = computed(() => store.deploy.rawStatus === 'DELETE_COMPLETE')
const canClean = computed(() => ['CREATE_FAILED', 'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED', 'CREATE_ROLLBACK_COMPLETE', 'CREATE_ROLLBACK_FAILED', 'DELETE_FAILED', 'DELETE_REQUESTED'].includes(store.deploy.rawStatus))
async function recover(action: 'credentials' | 'cleanup' | 'reset') {
  if (busy.value || !confirmed.value) return
  busy.value = true
  error.value = ''
  try {
    if (action === 'credentials') {
      await repairInstallCredentials(credentials.value, confirmation.value)
      credentials.value = { accessKeyId: '', accessKeySecret: '' }
      message.success('凭据已更新，继续查询原部署')
    } else if (action === 'cleanup') await cleanupInstallation(confirmation.value)
    else await resetInstallation(confirmation.value)
    emit('restored')
  } catch (e) { error.value = e instanceof Error ? e.message : '操作失败，请重试' }
  finally { busy.value = false }
}
</script>
<template>
  <section class="recovery">
    <h3>{{ deleted ? '旧资源已清理，可以重新配置' : '恢复这次部署' }}</h3>
    <p>当前状态：{{ store.deploy.rawStatus || '请求未确认' }}</p>
    <n-alert v-if="!deleted" type="warning" :show-icon="false">凭据错误时，可更新同一阿里云账号的凭据后继续原部署。清理会删除下方资源栈及其资源，无法撤销；确认删除完成后才能重新配置。</n-alert>
    <n-form-item :label="`输入 ${expected} 确认操作`" class="confirmation"><n-input v-model:value="confirmation" :placeholder="expected" :disabled="busy" /></n-form-item>
    <template v-if="!deleted">
      <div class="credentials">
        <n-form-item label="新的 AccessKey ID"><n-input v-model:value="credentials.accessKeyId" placeholder="输入同一云账号的 AccessKey ID" :disabled="busy" autocomplete="off" /></n-form-item>
        <n-form-item label="新的 AccessKey Secret"><n-input v-model:value="credentials.accessKeySecret" placeholder="输入新的 AccessKey Secret" type="password" show-password-on="click" :disabled="busy" autocomplete="new-password" /></n-form-item>
      </div>
      <n-space>
        <n-button :loading="busy" :disabled="busy || !confirmed || !credentials.accessKeyId.trim() || !credentials.accessKeySecret.trim()" @click="recover('credentials')">更新凭据并恢复</n-button>
        <n-button v-if="canClean && store.deploy.stackId" type="error" secondary :disabled="busy || !confirmed" @click="recover('cleanup')">删除失败的资源栈</n-button>
      </n-space>
    </template>
    <n-button v-else type="primary" :loading="busy" :disabled="busy || !confirmed" @click="recover('reset')">重新填写部署配置</n-button>
    <n-alert v-if="error" type="error" class="error">{{ error }}<br>若请求超时，请先点击“恢复查询”确认云端状态。</n-alert>
  </section>
</template>
<style scoped>
.recovery { border-top: 1px solid var(--n-border-color, #ddd); margin-top: 24px; padding-top: 20px; }
h3 { margin: 0 0 6px; }
p { opacity: .65; margin: 0 0 16px; overflow-wrap: anywhere; }
.confirmation { margin-top: 18px; }
.credentials { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.error { margin-top: 16px; }
@media (max-width: 600px) { .credentials { grid-template-columns: 1fr; gap: 0; } }
</style>
