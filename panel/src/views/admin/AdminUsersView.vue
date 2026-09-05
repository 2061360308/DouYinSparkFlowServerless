<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputGroup,
  NModal,
  NSpace,
  NTag,
  NText,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'

import { adminApi, type AdminUserRow } from '../../api/console'
import { ApiError } from '../../api/console.http'

const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const rows = ref<AdminUserRow[]>([])
const loading = ref(true)
const keyword = ref('')
const pagination = ref({ page: 1, pageCount: 1, pageSize: 8 })

const showCreate = ref(false)
const creating = ref(false)
const newUsername = ref('')

const showDelete = ref(false)
const deleteTarget = ref<AdminUserRow | null>(null)
const deleteConfirm = ref('')

function quotaText(row: AdminUserRow): string {
  if (row.role === 'admin') return '—'
  const limit = row.quota.limit === null ? '∞' : row.quota.limit
  return `${row.quota.active_usage}/${limit}`
}

const columns: DataTableColumns<AdminUserRow> = [
  { title: '用户名', key: 'username' },
  {
    title: '角色',
    key: 'role',
    width: 90,
    render: (r) =>
      h(NTag, { size: 'small', bordered: false, type: r.role === 'admin' ? 'warning' : 'default' },
        { default: () => (r.role === 'admin' ? '管理员' : '用户') }),
  },
  {
    title: '状态',
    key: 'status',
    width: 90,
    render: (r) =>
      h(NTag, { size: 'small', bordered: false, type: r.status === 'active' ? 'success' : 'error' },
        { default: () => (r.status === 'active' ? '正常' : '停用') }),
  },
  { title: '启用/额度', key: 'quota', width: 100, render: quotaText },
  {
    title: '操作',
    key: 'actions',
    width: 260,
    render: (row) => {
      if (row.role === 'admin') {
        return h(NButton, { size: 'small', tertiary: true, onClick: () => resetPassword(row) }, { default: () => '重置密码' })
      }
      return h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: 'small', tertiary: true, onClick: () => router.push({ name: 'admin-user-quota', params: { id: row.id } }) }, { default: () => '额度' }),
          h(NButton, { size: 'small', tertiary: true, onClick: () => resetPassword(row) }, { default: () => '重置密码' }),
          h(NButton, { size: 'small', tertiary: true, type: row.status === 'active' ? 'warning' : 'success', onClick: () => toggle(row) }, { default: () => (row.status === 'active' ? '停用' : '启用') }),
          h(NButton, { size: 'small', tertiary: true, type: 'error', onClick: () => openDelete(row) }, { default: () => '删除' }),
        ],
      })
    },
  },
]

async function load(page = 1) {
  loading.value = true
  try {
    const res = await adminApi.users(keyword.value.trim(), page)
    rows.value = res.items
    pagination.value.page = res.page.page
    pagination.value.pageCount = res.page.pages
  } catch {
    message.error('加载失败')
  } finally {
    loading.value = false
  }
}

function showTempPassword(username: string, password: string) {
  dialog.success({
    title: '临时密码',
    content: `用户「${username}」的初始/临时密码：\n${password}\n请复制并转交，用户登录后需修改。`,
    positiveText: '我已复制',
  })
}

async function createUser() {
  if (!newUsername.value.trim()) return message.warning('请输入用户名')
  creating.value = true
  try {
    const res = await adminApi.createUser(newUsername.value.trim())
    showCreate.value = false
    newUsername.value = ''
    await load(1)
    showTempPassword(newUsername.value.trim() || '新用户', res.temporary_password)
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '创建失败')
  } finally {
    creating.value = false
  }
}

function resetPassword(row: AdminUserRow) {
  dialog.warning({
    title: '重置密码',
    content: `确认重置「${row.username}」的密码？将生成新的临时密码并使其重新登录。`,
    positiveText: '重置',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const res = await adminApi.resetPassword(row.id)
        showTempPassword(row.username, res.temporary_password)
      } catch (error) {
        message.error(error instanceof ApiError ? error.detail : '重置失败')
      }
    },
  })
}

async function toggle(row: AdminUserRow) {
  try {
    await adminApi.toggleUser(row.id)
    await load(pagination.value.page)
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '操作失败')
  }
}

function openDelete(row: AdminUserRow) {
  deleteTarget.value = row
  deleteConfirm.value = ''
  showDelete.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  try {
    await adminApi.deleteUser(deleteTarget.value.id, deleteConfirm.value.trim())
    message.success('已删除')
    showDelete.value = false
    await load(pagination.value.page)
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '删除失败')
  }
}

onMounted(() => load(1))
</script>

<template>
  <n-card title="用户管理">
    <template #header-extra>
      <n-button type="primary" @click="showCreate = true">新建用户</n-button>
    </template>
    <n-input-group class="search">
      <n-input v-model:value="keyword" placeholder="搜索用户名" clearable @keyup.enter="load(1)" />
      <n-button @click="load(1)">搜索</n-button>
    </n-input-group>
    <n-data-table
      remote
      :columns="columns"
      :data="rows"
      :loading="loading"
      :bordered="false"
      :pagination="pagination"
      @update:page="load"
    />
  </n-card>

  <n-modal v-model:show="showCreate" preset="card" title="新建用户" style="max-width: 420px">
    <n-form :model="{ newUsername }" label-placement="top">
      <n-form-item label="用户名（3–32 位字母/数字/_/-）">
        <n-input v-model:value="newUsername" placeholder="用户名" @keyup.enter="createUser" />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showCreate = false">取消</n-button>
        <n-button type="primary" :loading="creating" @click="createUser">创建</n-button>
      </n-space>
    </template>
  </n-modal>

  <n-modal v-model:show="showDelete" preset="card" title="删除用户" style="max-width: 440px">
    <n-text>此操作不可恢复，将删除该用户及其账号、任务。请输入用户名</n-text>
    <n-text strong> {{ deleteTarget?.username }} </n-text>
    <n-text>以确认：</n-text>
    <n-input v-model:value="deleteConfirm" placeholder="输入用户名确认" style="margin-top: 12px" />
    <template #footer>
      <n-space justify="end">
        <n-button @click="showDelete = false">取消</n-button>
        <n-button
          type="error"
          :disabled="deleteConfirm.trim() !== deleteTarget?.username"
          @click="confirmDelete"
        >
          删除
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.search {
  max-width: 320px;
  margin-bottom: 14px;
}
</style>
