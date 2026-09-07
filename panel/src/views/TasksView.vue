<script setup lang="ts">
import { computed, h, onMounted, onUnmounted, ref, watch } from 'vue'
import {
  NButton,
  NAlert,
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
  type ConversationItem,
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
const loadError = ref('')
const busyIds = ref(new Set<string>())
const search = ref('')
const filter = ref('all')
const pendingCount = computed(() => tasks.value.filter(t => t.schedule_state !== 'synced').length)
const enabledCount = computed(() => tasks.value.filter(t => t.enabled).length)
const visibleTasks = computed(() => tasks.value.filter(t =>
  (!search.value || `${t.target_name} ${t.message_template}`.includes(search.value.trim())) &&
  (filter.value === 'all' || (filter.value === 'enabled' ? t.enabled : t.schedule_state !== 'synced')),
))

const showEdit = ref(false)
const editingId = ref<string | null>(null)
const submitting = ref(false)
const form = ref({ account_id: '', target_name: '', target_sec_uid: '', send_time: '', message_template: '' })
const availability = ref<Availability | null>(null)
const contacts = ref<ConversationItem[]>([])
const contactsLoading = ref(false)
const contactsSyncing = ref(false)
const contactError = ref('')
let contactVersion = 0
const contactOptions = computed(() => contacts.value.filter(c => c.sec_uid).map(c => ({
  label: `${c.name} · ${c.sec_uid!.slice(-8)}`, value: c.sec_uid!,
})))

async function loadContacts(sync = false) {
  const version = ++contactVersion
  const account = form.value.account_id
  contacts.value = []
  contactError.value = ''
  if (!account || !showEdit.value) { contactsLoading.value = false; contactsSyncing.value = false; return }
  contactsLoading.value = true
  contactsSyncing.value = sync
  try {
    if (sync) await accountApi.syncConversations(account)
    const result = await accountApi.conversations(account)
    if (version === contactVersion) contacts.value = result.items
  } catch (error) {
    if (version === contactVersion) contactError.value = error instanceof ApiError ? error.detail : '好友列表加载失败，请重试'
  } finally {
    if (version === contactVersion) { contactsLoading.value = false; contactsSyncing.value = false }
  }
}
function selectContact(uid: string) {
  const contact = contacts.value.find(c => c.sec_uid === uid)
  form.value.target_sec_uid = contact?.sec_uid ?? ''
  form.value.target_name = contact?.name.slice(0, 64) ?? ''
}
watch(() => [form.value.account_id, showEdit.value], () => loadContacts())

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
    width: 70,
    render: (row) => h('b', { class: 'task-time' }, row.send_time),
  },
  { title: '好友', key: 'target_name', width: 120 },
  {
    title: '消息',
    key: 'message_template',
    ellipsis: { tooltip: true },
  },
  {
    title: '状态',
    key: 'enabled',
    width: 80,
    render: (row) =>
      h(NTag, { type: row.enabled ? 'success' : 'default', bordered: false, size: 'small' },
        { default: () => (row.enabled ? '启用' : '暂停') }),
  },
  {
    title: '调度', key: 'schedule_state', width: 116,
    render: row => h(NTag, { size: 'small', bordered: false, type: row.schedule_state === 'synced' ? 'success' : 'warning', title: row.schedule_error },
      { default: () => row.schedule_state === 'synced' ? (row.enabled ? '已就绪' : '已停止') : '待同步' }),
  },
  {
    title: '操作',
    key: 'actions',
    width: 248,
    render: (row) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, { size: 'small', tertiary: true, disabled: busyIds.value.has(row.id), onClick: () => openEdit(row) }, { default: () => '编辑' }),
          h(NButton, { size: 'small', tertiary: true, disabled: busyIds.value.has(row.id), type: row.enabled ? 'warning' : 'success', onClick: () => toggle(row) },
            { default: () => (row.enabled ? '暂停' : '启用') }),
          ...(row.schedule_state !== 'synced' ? [h(NButton, { size: 'small', disabled: busyIds.value.has(row.id), onClick: () => retrySync(row) }, { default: () => '同步' })] : []),
          h(NButton, { size: 'small', tertiary: true, disabled: busyIds.value.has(row.id), type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
        ],
      }),
  },
]

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [taskRes, accRes] = await Promise.all([taskApi.list(), accountApi.list()])
    tasks.value = taskRes.items
    quota.value = taskRes.quota
    accounts.value = accRes.items
  } catch {
    loadError.value = '任务加载失败，请检查连接后重试。'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = { account_id: accounts.value[0]?.id ?? '', target_name: '', target_sec_uid: '', send_time: '', message_template: '' }
  availability.value = null
  showEdit.value = true
}

function openEdit(row: TaskItem) {
  editingId.value = row.id
  form.value = {
    account_id: row.account_id ?? '',
    target_name: row.target_name,
    target_sec_uid: row.target_sec_uid,
    send_time: row.send_time,
    message_template: row.message_template,
  }
  availability.value = null
  showEdit.value = true
}

let availTimer: ReturnType<typeof setTimeout> | null = null
let availabilityVersion = 0
watch(
  () => [form.value.send_time, editingId.value, showEdit.value] as const,
  ([value, taskId, open]) => {
    const version = ++availabilityVersion
    availability.value = null
    if (availTimer) clearTimeout(availTimer)
    if (!open || !/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return
    availTimer = setTimeout(async () => {
      try {
        const result = await taskApi.availability(value, taskId ?? '')
        if (version === availabilityVersion) availability.value = result
      } catch {
        /* ignore */
      }
    }, 250)
  },
)
onUnmounted(() => { contactVersion++; availabilityVersion++; if (availTimer) clearTimeout(availTimer) })

async function submit() {
  if (submitting.value) return
  if (!form.value.account_id) return message.warning('请选择抖音账号')
  if (!form.value.target_name.trim()) return message.warning('请填写好友名称')
  if (!form.value.target_sec_uid) return message.warning('请选择带稳定 ID 的好友')
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(form.value.send_time)) return message.warning('请选择发送时间')
  if (!form.value.message_template.trim()) return message.warning('请填写消息内容')
  submitting.value = true
  try {
    const body = {
      account_id: form.value.account_id,
      target_name: form.value.target_name.trim(),
      target_sec_uid: form.value.target_sec_uid,
      send_time: form.value.send_time,
      message_template: form.value.message_template.trim(),
    }
    const saved = editingId.value ? await taskApi.update(editingId.value, body) : await taskApi.create(body)
    if (saved.schedule_state !== 'synced') message.warning('任务已保存，调度待同步，请点击任务旁的“同步”重试')
    else message.success('任务和调度已保存')
    showEdit.value = false
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '保存失败')
  } finally {
    submitting.value = false
  }
}

async function toggle(row: TaskItem) {
  if (busyIds.value.has(row.id)) return
  busyIds.value.add(row.id)
  try {
    const result = await taskApi.toggle(row.id)
    if (result.schedule_state !== 'synced') message.warning(result.schedule_error)
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '操作失败')
  } finally { busyIds.value.delete(row.id) }
}

async function retrySync(row: TaskItem) {
  if (busyIds.value.has(row.id)) return
  busyIds.value.add(row.id)
  try {
    const result = await taskApi.sync(row.id)
    if (result.schedule_state === 'synced') message.success('调度已同步')
    else message.warning(result.schedule_error)
    await load()
  } catch (error) { message.error(error instanceof ApiError ? error.detail : '同步失败') }
  finally { busyIds.value.delete(row.id) }
}

function confirmDelete(row: TaskItem) {
  dialog.warning({
    title: '删除任务',
    content: `确认删除给「${row.target_name}」的续火任务？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      if (busyIds.value.has(row.id)) return false
      busyIds.value.add(row.id)
      try {
        await taskApi.remove(row.id)
        message.success('已删除')
        await load()
      } catch (error) {
        message.error(error instanceof ApiError ? error.detail : '删除失败')
        await load()
        return false
      } finally { busyIds.value.delete(row.id) }
    },
  })
}

onMounted(load)
</script>

<template>
  <div class="task-heading"><div><span class="eyebrow">DAILY ROUTINE</span><h1>每天的约定，按时续上。</h1><p>管理发送时间、好友和消息，确认每个任务的调度状态。</p></div><div class="task-totals"><strong>{{ enabledCount }}</strong><span>启用任务</span><strong>{{ pendingCount }}</strong><span>待同步</span></div></div>
  <n-card title="续火任务">
    <template #header-extra>
      <n-space align="center">
        <n-text depth="3">{{ quotaText }}</n-text>
        <n-button type="primary" :disabled="accounts.length === 0" @click="openCreate">新建任务</n-button>
      </n-space>
    </template>
    <n-alert v-if="loadError" type="error" class="task-alert">{{ loadError }} <n-button text @click="load">重新加载</n-button></n-alert>
    <n-alert v-else-if="pendingCount" type="warning" class="task-alert">{{ pendingCount }} 个任务尚未同步，请点击任务旁的“同步”重试。暂停后不再启动新的执行，正在执行的任务不会中断。</n-alert>
    <div class="task-toolbar"><n-input v-model:value="search" clearable placeholder="搜索好友或消息" aria-label="搜索任务" /><n-select v-model:value="filter" :options="[{ label: '全部任务', value: 'all' }, { label: '已启用', value: 'enabled' }, { label: '待同步', value: 'pending' }]" aria-label="筛选任务" /><n-button :loading="loading" @click="load">刷新</n-button></div>
    <n-data-table :columns="columns" :data="visibleTasks" :loading="loading" :bordered="false" :scroll-x="850" :pagination="{ pageSize: 10 }">
      <template #empty>{{ search || filter !== 'all' ? '没有符合条件的任务，试试其他筛选。' : '还没有续火任务，选择好友和时间，创建第一条每日计划。' }}</template>
    </n-data-table>
    <n-text v-if="accounts.length === 0" depth="3" class="tip">请先在「抖音账号」添加账号后再创建任务。</n-text>
  </n-card>

  <n-modal
    v-model:show="showEdit"
    preset="card"
    :title="editingId ? '编辑任务' : '新建任务'"
    :style="{ maxWidth: 'min(560px, calc(100vw - 32px))', width: '90vw' }"
  >
    <n-form :model="form" label-placement="top">
      <n-form-item label="抖音账号">
        <n-select v-model:value="form.account_id" :options="accountOptions" placeholder="选择账号" @update:value="form.target_sec_uid = ''; form.target_name = ''" />
      </n-form-item>
      <n-form-item label="好友名称 / 备注">
        <n-select :value="form.target_sec_uid || null" :options="contactOptions" filterable
          :loading="contactsLoading" :disabled="contactsLoading" placeholder="选择已绑定 ID 的好友" @update:value="selectContact" />
      </n-form-item>
      <n-alert v-if="contactError" type="warning">{{ contactError }}</n-alert>
      <n-space style="margin-bottom: 16px">
        <n-button :loading="contactsSyncing" :disabled="contactsLoading || !form.account_id" @click="loadContacts(true)">同步可见会话</n-button>
        <n-text depth="3">只同步能识别 ID 的当前会话；缺失 ID 的旧任务需重新选择好友。</n-text>
      </n-space>
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
.task-heading { display: flex; justify-content: space-between; align-items: center; gap: 24px; margin-bottom: 28px; }
.eyebrow { font: 11px Consolas, monospace; letter-spacing: .13em; color: #b76a31; }
h1 { font-size: 26px; margin: 10px 0 6px; letter-spacing: -.025em; }
.task-heading p { margin: 0; opacity: .6; }
.task-totals { display: grid; grid-template-columns: auto auto; gap: 6px 14px; align-items: baseline; white-space: nowrap; }
.task-totals strong { font: 28px Consolas, monospace; }
.task-totals span { font-size: 12px; opacity: .6; }
.task-toolbar { display: grid; grid-template-columns: minmax(160px, 1fr) 150px auto; gap: 12px; margin-bottom: 18px; }
.task-alert { margin-bottom: 18px; }
:deep(.task-time) { font: 600 16px Consolas, monospace; font-variant-numeric: tabular-nums; }
@media (max-width: 650px) { .task-heading { align-items: flex-start; } h1 { font-size: 21px; } .task-totals { display: none; } .task-toolbar { grid-template-columns: 1fr auto; } .task-toolbar > :first-child { grid-column: 1 / -1; } }
.tip {
  display: block;
  margin-top: 10px;
  font-size: 13px;
}
</style>
