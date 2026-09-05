<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NInput, useMessage, type FormInst, type FormRules } from 'naive-ui'

import { authApi } from '../api/console'
import { useAuth } from '../composables/useAuth'
import { ApiError } from '../api/console.http'

const router = useRouter()
const message = useMessage()
const { state, refresh } = useAuth()

const formRef = ref<FormInst | null>(null)
const model = ref({ current: '', next: '', confirm: '' })
const loading = ref(false)

const rules: FormRules = {
  current: { required: true, message: '请输入当前密码', trigger: ['blur'] },
  next: [
    { required: true, message: '请输入新密码', trigger: ['blur'] },
    { min: 12, message: '新密码至少 12 位', trigger: ['blur', 'input'] },
  ],
  confirm: {
    required: true,
    trigger: ['blur', 'input'],
    validator: (_r, value: string) => value === model.value.next || new Error('两次输入的新密码不一致'),
  },
}

async function submit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await authApi.changePassword(model.value.current, model.value.next, model.value.confirm)
    await refresh()
    message.success('密码已更新')
    router.replace({ name: 'dashboard' })
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <n-card title="修改密码" class="card">
      <p v-if="state.mustChangePassword" class="hint">首次登录或密码被重置，请先设置新密码。</p>
      <n-form ref="formRef" :model="model" :rules="rules" label-placement="top">
        <n-form-item label="当前密码" path="current">
          <n-input v-model:value="model.current" type="password" show-password-on="click" />
        </n-form-item>
        <n-form-item label="新密码（至少 12 位）" path="next">
          <n-input v-model:value="model.next" type="password" show-password-on="click" />
        </n-form-item>
        <n-form-item label="确认新密码" path="confirm">
          <n-input v-model:value="model.confirm" type="password" show-password-on="click" />
        </n-form-item>
        <n-button type="primary" block :loading="loading" @click="submit">保存</n-button>
      </n-form>
    </n-card>
  </div>
</template>

<style scoped>
.wrap {
  display: flex;
  justify-content: center;
}
.card {
  width: 460px;
  max-width: 100%;
}
.hint {
  margin: 0 0 14px;
  font-size: 13px;
  color: #d99a00;
}
</style>
