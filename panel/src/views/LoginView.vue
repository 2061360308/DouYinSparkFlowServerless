<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NForm, NFormItem, NIcon, NInput, useMessage, type FormInst } from 'naive-ui'
import { FlameOutline } from '@vicons/ionicons5'

import { useAuth } from '../composables/useAuth'
import { ApiError } from '../api/console.http'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const { login } = useAuth()

const formRef = ref<FormInst | null>(null)
const model = ref({ username: '', password: '' })
const loading = ref(false)

const rules = {
  username: { required: true, message: '请输入用户名', trigger: ['blur', 'input'] },
  password: { required: true, message: '请输入密码', trigger: ['blur', 'input'] },
}

async function submit() {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    await login(model.value.username.trim(), model.value.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    router.replace(redirect)
  } catch (error) {
    const detail = error instanceof ApiError ? error.detail : '登录失败，请重试'
    message.error(detail)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="backdrop" />
    <n-card class="login-card" :bordered="false">
      <div class="brand">
        <n-icon :size="30" :component="FlameOutline" color="#aa3bff" />
        <div class="brand-name">DouyinSpark 控制台</div>
      </div>
      <p class="subtitle">登录以管理抖音账号与续火任务</p>
      <n-form ref="formRef" :model="model" :rules="rules" @keyup.enter="submit">
        <n-form-item label="用户名" path="username">
          <n-input v-model:value="model.username" placeholder="请输入用户名" />
        </n-form-item>
        <n-form-item label="密码" path="password">
          <n-input
            v-model:value="model.password"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
          />
        </n-form-item>
        <n-button type="primary" block strong :loading="loading" @click="submit">登录</n-button>
      </n-form>
    </n-card>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.backdrop {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(1200px 600px at 20% -10%, rgba(170, 59, 255, 0.22), transparent 60%),
    radial-gradient(900px 500px at 90% 110%, rgba(120, 90, 255, 0.18), transparent 55%);
  z-index: 0;
}
.login-card {
  position: relative;
  z-index: 1;
  width: 380px;
  max-width: calc(100vw - 32px);
  border-radius: 14px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.14);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-name {
  font-size: 20px;
  font-weight: 700;
}
.subtitle {
  margin: 6px 0 22px;
  font-size: 13px;
  opacity: 0.65;
}
</style>
