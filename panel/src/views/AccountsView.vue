<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSpace,
  NTag,
  useDialog,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'

import { accountApi, type AccountItem } from '../api/console'
import { ApiError } from '../api/console.http'

const message = useMessage()
const dialog = useDialog()

const rows = ref<AccountItem[]>([])
const loading = ref(true)
const showAdd = ref(false)
const submitting = ref(false)
const form = ref({ display_name: '', cookies: '' })

const STATE = {
  valid: { label: '有效', type: 'success' as const },
  invalid: { label: '失效', type: 'error' as const },
  unknown: { label: '未验证', type: 'default' as const },
}

const columns: DataTableColumns<AccountItem> = [
  { title: '名称', key: 'display_name' },
  {
    title: '状态',
    key: 'validation_state',
    width: 120,
    render(row) {
      const meta = STATE[row.validation_state as keyof typeof STATE] ?? STATE.unknown
      return h(NTag, { type: meta.type, bordered: false, size: 'small' }, { default: () => meta.label })
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render(row) {
      return h(
        NButton,
        { size: 'small', tertiary: true, type: 'error', onClick: () => confirmDelete(row) },
        { default: () => '删除' },
      )
    },
  },
]

async function load() {
  loading.value = true
  try {
    rows.value = (await accountApi.list()).items
  } catch {
    message.error('加载失败')
  } finally {
    loading.value = false
  }
}

function openAdd() {
  form.value = { display_name: '', cookies: '' }
  showAdd.value = true
}

async function submit() {
  if (!form.value.display_name.trim()) {
    message.warning('请填写账号名称')
    return
  }
  submitting.value = true
  try {
    await accountApi.create(form.value.display_name.trim(), form.value.cookies.trim())
    message.success('已添加')
    showAdd.value = false
    await load()
  } catch (error) {
    message.error(error instanceof ApiError ? error.detail : '添加失败')
  } finally {
    submitting.value = false
  }
}

function confirmDelete(row: AccountItem) {
  dialog.warning({
    title: '删除账号',
    content: `确认删除「${row.display_name}」？其关联任务会被停用并解绑。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await accountApi.remove(row.id)
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
  <n-card title="抖音账号">
    <template #header-extra>
      <n-button type="primary" @click="openAdd">添加账号</n-button>
    </template>
    <n-data-table :columns="columns" :data="rows" :loading="loading" :bordered="false" scroll-x="auto" />
  </n-card>

  <n-modal v-model:show="showAdd" preset="card" title="添加抖音账号" :style="{ maxWidth: 'min(560px, calc(100vw - 32px))', width: '90vw' }">
    <n-form :model="form" label-placement="top">
      <n-form-item label="账号名称">
        <n-input v-model:value="form.display_name" placeholder="用于区分的名称" />
      </n-form-item>
      <n-form-item label="Cookie（JSON 数组）">
        <n-input
          v-model:value="form.cookies"
          type="textarea"
          :rows="6"
          placeholder='[{"name":"...","value":"..."}]'
        />
      </n-form-item>
    </n-form>
    <template #footer>
      <n-space justify="end">
        <n-button @click="showAdd = false">取消</n-button>
        <n-button type="primary" :loading="submitting" @click="submit">保存</n-button>
      </n-space>
    </template>
  </n-modal>
</template>
