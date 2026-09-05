<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDataTable,
  NDatePicker,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NPageHeader,
  NSpace,
  NStatistic,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'

import { adminApi, type QuotaGrant, type QuotaSummary } from '../../api/console'
import { ApiError } from '../../api/console.http'
import { formatDateTime } from '../../utils/format'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const userId = route.params.id as string
const username = ref('')
const quota = ref<QuotaSummary | null>(null)
const loading = ref(true)

const limitInput = ref<number | null>(null)
const savingLimit = ref(false)

const grantForm = ref<{ amount: number; starts_at: number | null; expires_at: number | null; label: string }>({
  amount: 5,
  starts_at: Date.now(),
  expires_at: null,
  label: '',
})
const adding = ref(false)

const STATUS: Record<string, { label: string; type: 'default' | 'success' | 'warning' | 'error' | 'info' }> = {
  active: { label: '生效中', type: 'success' },
  expiring: { label: '即将到期', type: 'warning' },
  future: { label: '未开始', type: 'info' },
  expired: { label: '已过期', type: 'default' },
  revoked: { label: '已撤销', type: 'error' },
}

const grantColumns: DataTableColumns<QuotaGrant> = [
  { title: '名称', key: 'label' },
  { title: '额度', key: 'amount', width: 70 },
  { title: '开始', key: 'starts_at', width: 170, render: (g) => formatDateTime(g.starts_at) },
  { title: '到期', key: 'expires_at', width: 170, render: (g) => (g.expires_at ? formatDateTime(g.expires_at) : '永久') },
  {
    title: '状态',
    key: 'status',
    width: 100,
    render: (g) => {
      const meta = STATUS[g.status] ?? STATUS.expired
      return h(NTag, { size: 'small', bordered: false, type: meta.type }, { default: () => meta.label })
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 90,
    render: (g) =>
      g.status === 'revoked'
        ? '—'
        : h(NButton, { size: 'small', tertiary: true, type: 'error', onClick: () => revoke(g) }, { default: () => '撤销' }),
  },
]

const limitDisplay = computed(() => (quota.value?.limit === null ? '∞' : quota.value?.limit ?? 0))

async function load() {
  loading.value = true
  try {
    const res = await adminApi.userQuota(userId)
    username.value = res.user.username
    quota.value = res.quota
    limitInput.value = res.quota.limit
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '加载失败')
    router.replace({ name: 'admin-users' })
  } finally {
    loading.value = false
  }
}

async function saveLimit() {
  if (limitInput.value == null || limitInput.value < 1) return message.warning('请输入有效上限')
  savingLimit.value = true
  try {
    await adminApi.setTaskLimit(userId, limitInput.value)
    message.success('已更新任务上限')
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '更新失败')
  } finally {
    savingLimit.value = false
  }
}

async function addGrant() {
  if (!grantForm.value.amount || grantForm.value.amount < 1) return message.warning('额度须 ≥ 1')
  if (!grantForm.value.starts_at) return message.warning('请选择开始时间')
  if (!grantForm.value.label.trim()) return message.warning('请填写名称')
  adding.value = true
  try {
    await adminApi.addGrant(userId, {
      amount: grantForm.value.amount,
      starts_at: new Date(grantForm.value.starts_at).toISOString(),
      expires_at: grantForm.value.expires_at ? new Date(grantForm.value.expires_at).toISOString() : undefined,
      label: grantForm.value.label.trim(),
    })
    message.success('已添加额度')
    grantForm.value = { amount: 5, starts_at: Date.now(), expires_at: null, label: '' }
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '添加失败')
  } finally {
    adding.value = false
  }
}

function revoke(g: QuotaGrant) {
  dialog.warning({
    title: '撤销额度',
    content: `撤销「${g.label}」后，超额的启用任务会被自动暂停。`,
    positiveText: '撤销',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await adminApi.revokeGrant(g.id)
        message.success('已撤销')
        await load()
      } catch (error) {
        message.error(error instanceof ApiError ? error.detail : '撤销失败')
      }
    },
  })
}

onMounted(load)
</script>

<template>
  <div class="quota">
    <n-page-header :title="`${username} 的任务额度`" @back="router.push({ name: 'admin-users' })" />

    <n-grid cols="1 s:3" responsive="screen" :x-gap="14" :y-gap="14">
      <n-gi>
        <n-card><n-statistic label="当前上限" :value="limitDisplay" /></n-card>
      </n-gi>
      <n-gi>
        <n-card><n-statistic label="启用中" :value="quota?.active_usage ?? 0" /></n-card>
      </n-gi>
      <n-gi>
        <n-card><n-statistic label="已保存" :value="quota?.saved_usage ?? 0" /></n-card>
      </n-gi>
    </n-grid>

    <n-card title="快速设置任务上限" size="small">
      <n-space align="center">
        <n-input-number v-model:value="limitInput" :min="1" :max="100" />
        <n-button type="primary" :loading="savingLimit" @click="saveLimit">保存</n-button>
      </n-space>
    </n-card>

    <n-card title="额度授予">
      <n-data-table :columns="grantColumns" :data="quota?.grants ?? []" :loading="loading" :bordered="false" />
    </n-card>

    <n-card title="新增额度" size="small">
      <n-form :model="grantForm" label-placement="left" label-width="80" :show-feedback="false">
        <n-grid cols="1 s:2" responsive="screen" :x-gap="14" :y-gap="12">
          <n-gi>
            <n-form-item label="额度">
              <n-input-number v-model:value="grantForm.amount" :min="1" :max="100" style="width: 100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="名称">
              <n-input v-model:value="grantForm.label" placeholder="如：活动赠送" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="开始">
              <n-date-picker v-model:value="grantForm.starts_at" type="datetime" style="width: 100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="到期">
              <n-date-picker
                v-model:value="grantForm.expires_at"
                type="datetime"
                clearable
                placeholder="留空为永久"
                style="width: 100%"
              />
            </n-form-item>
          </n-gi>
        </n-grid>
        <div class="add-actions">
          <n-button type="primary" :loading="adding" @click="addGrant">新增额度</n-button>
        </div>
      </n-form>
    </n-card>
  </div>
</template>

<style scoped>
.quota {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.add-actions {
  margin-top: 14px;
  text-align: right;
}
</style>
