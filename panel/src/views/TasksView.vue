<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NTag,
  NText,
  NTimePicker,
  useDialog,
  useMessage,
  type DataTableColumns,
  type SelectOption,
} from 'naive-ui'

import {
  accountApi,
  taskApi,
  type AccountItem,
  type Availability,
  type QuotaSummary,
  type TaskItem,
} from '../api/console'
import { ApiError } from '../api/console.http'

const message = useMessage()
const dialog = useDialog()

const tasks = ref<TaskItem[]>([])
const quota = ref<QuotaSummary | null>(null)
const accounts = ref<AccountItem[]>([])
const loading = ref(true)

const showEdit = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const form = ref({ account_id: '', target_name: '', send_time: '', message_template: '' })
const availability = ref<Availability | null>(null)

const accountOptions = computed<SelectOption[]>(() =>
  accounts.value.map((a) => ({ label: a.display_name, value: a.id })),
)

const quotaText = computed(() => {
  if (!quota.value) return ''
  const limit = quota.value.limit === null ? '∞' : quota.value.limit
  return `启用 ${quota.value.active_usage}/${limit} · 已保存 ${quota.value.saved_usage}/${quota.value.max_saved_tasks}`
})

const columns: DataTableColumns<TaskItem> = [
  {
    title: '时间',
    key: 'send_time',
    width: 84,
    render: (row) => h('b', { style: 'color:#aa3bff' }, row.send_time),
  },
  { title: '好友', key: 'target_name', width: 140 },
  {
    title: '消息',
    key: 'message_template',
    ellipsis: { tooltip: true },
  },
  {
    title: '状态',
    key: 'enabled',
    width: 90,
    render: (row) =>
      h(NTag, { type: row.enabled ? 'success' : 'default', bordered: false, size: 'small' },
        { default: () => (row.enabled ? '启用' : '暂停') }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 190,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: 'small', tertiary: true, onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NButton, { size: 'small', tertiary: true, type: row.enabled ? 'warning' : 'success', onClick: () => toggle(row) },
            { default: () => (row.enabled ? '暂停' : '启用') }),
          h(NButton, { size: 'small', tertiary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
        ],
      }),
  },
]

async function load() {
  loading.value = true
  try {
    const [taskRes, accRes] = await Promise.all([taskApi.list(), accountApi.list()])
    tasks.value = taskRes.items
    quota.value = taskRes.quota
    accounts.value = accRes.items
  } catch {
    message.error('加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = { account_id: accounts.value[0]?.id ?? '', target_name: '', send_time: '', message_template: '' }
  availability.value = null
  showEdit.value = true
}

function openEdit(row: TaskItem) {
  editingId.value = row.id
  form.value = {
    account_id: row.account_id ?? '',
    target_name: row.target_name,
    send_time: row.send_time,
    message_template: row.message_template,
  }
  availability.value = null
  showEdit.value = true
}

let availTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => form.value.send_time,
  (value) => {
    availability.value = null
    if (availTimer) clearTimeout(availTimer)
    if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return
    availTimer = setTimeout(async () => {
      try {
        availability.value = await taskApi.availability(value, editingId.value ?? '')
      } catch {
        /* ignore */
      }
    }, 250)
  },
)

async function submit() {
  if (!form.value.account_id) return message.warning('请选择抖音账号')
  if (!form.value.target_name.trim()) return message.warning('请填写好友名称')
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(form.value.send_time)) return message.warning('请选择发送时间')
  if (!form.value.message_template.trim()) return message.warning('请填写消息内容')
  submitting.value = true
  try {
    const body = {
      account_id: form.value.account_id,
      target_name: form.value.target_name.trim(),
      send_time: form.value.send_time,
      message_template: form.value.message_template.trim(),
    }
    if (editingId.value) {
      await taskApi.update(editingId.value, body)
    } else {
      await taskApi.create(body)
    }
    message.success('已保存')
    showEdit.value = false
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '保存失败')
  } finally {
    submitting.value = false
  }
}

async function toggle(row: TaskItem) {
  try {
    await taskApi.toggle(row.id)
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '操作失败')
  }
}

function confirmDelete(row: TaskItem) {
  dialog.warning({
    title: '删除任务',
    content: `确认删除给「${row.target_name}」的续火任务？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await taskApi.remove(row.id)
        message.success('已删除')
        await load()
      } catch (error) {
        message.error(error instanceof ApiError ? error.detail : '删除失败')
      }
    },
  })
}

onMounted(load)
</script>

<template>
  <n-card title="续火任务">
    <template #header-extra>
      <n-space align="center">
        <n-text depth="3">{{ quotaText }}</n-text>
        <n-button type="primary" :disabled="accounts.length === 0" @click="openCreate">新建任务</n-button>
      </n-space>
    </template>
    <n-data-table :columns="columns" :data="tasks" :loading="loading" :bordered="false" />
    <n-text v-if="accounts.length === 0" depth="3" class="tip">请先在「抖音账号」添加账号后再创建任务。</n-text>
  </n-card>

  <n-modal
    v-model:show="showEdit"
    preset="card"
    :title="editingId ? '编辑任务' : '新建任务'"
    style="max-width: 560px"
  >
    <n-form :model="form" label-placement="top">
      <n-form-item label="抖音账号">
        <n-select v-model:value="form.account_id" :options="accountOptions" placeholder="选择账号" />
      </n-form-item>
      <n-form-item label="好友名称 / 备注">
        <n-input v-model:value="form.target_name" placeholder="聊天列表中显示的名称" />
      </n-form-item>
      <n-form-item label="每日发送时间">
        <n-time-picker
          v-model:formatted-value="form.send_time"
          format="HH:mm"
          value-format="HH:mm"
          placeholder="选择时间"
          style="width: 100%"
        />
      </n-form-item>
      <n-form-item v-if="availability" :show-label="false" :show-feedback="false">
        <n-text v-if="availability.available" type="success">✓ 该时间可用</n-text>
        <div v-else>
          <n-text type="error">该时间与其它任务不足 4 分钟间隔，建议：</n-text>
          <n-space size="small" style="margin-top: 6px">
            <n-tag
              v-for="s in availability.suggestions"
              :key="s"
              checkable
              @click="form.send_time = s"
            >
              {{ s }}
            </n-tag>
          </n-space>
        </div>
      </n-form-item>
      <n-form-item label="消息内容">
        <n-input
          v-model:value="form.message_template"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-count
          placeholder="每天自动发送的消息"
        />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showEdit = false">取消</n-button>
        <n-button type="primary" :loading="submitting" @click="submit">保存</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.tip {
  display: block;
  margin-top: 10px;
  font-size: 13px;
}
</style>
