<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NAlert, NButton, NCard, NDataTable, NTag, useMessage, type DataTableColumns } from 'naive-ui'

import { runApi, type RunItem } from '../api/console'
import { formatDateTime, RUN_STATUS_LABEL, RUN_STATUS_TYPE } from '../utils/format'

const message = useMessage()
const rows = ref<RunItem[]>([])
const loading = ref(true)
const showOwner = ref(false)
const pagination = ref({ page: 1, pageCount: 1, pageSize: 6 })

const columns = ref<DataTableColumns<RunItem>>([])
const deliveryLabels: Record<string, string> = { accepted: '服务端已接收', delivered: '送达回执', read: '已读回执' }

function buildColumns() {
  const cols: DataTableColumns<RunItem> = [
    { title: '计划时间', key: 'scheduled_for', width: 150, render: (r) => formatDateTime(r.scheduled_for) },
    { title: '好友', key: 'target_name', width: 120, render: (r) => r.target_name ?? '—' },
  ]
  if (showOwner.value) {
    cols.push({ title: '所属用户', key: 'owner_username', width: 120, render: (r) => r.owner_username ?? '—' })
  }
  cols.push(
    {
      title: '状态',
      key: 'status',
      width: 100,
      render: (r) =>
        h(NTag, { type: RUN_STATUS_TYPE[r.status] ?? 'default', bordered: false, size: 'small' },
          { default: () => RUN_STATUS_LABEL[r.status] ?? r.status }),
    },
    { title: '说明', key: 'error_summary', ellipsis: { tooltip: true }, render: (r) => r.error_summary ?? '—' },
    { title: '送达证据', key: 'delivery_level', width: 130, render: (r) =>
      (deliveryLabels[r.delivery_level ?? ''] ?? '暂无服务端回执') },
  )
  columns.value = cols
}

async function load(page = 1) {
  loading.value = true
  try {
    const res = await runApi.list(page)
    rows.value = res.items
    showOwner.value = res.show_owner
    pagination.value.page = res.page.page
    pagination.value.pageCount = res.page.pages
    buildColumns()
  } catch {
    message.error('加载失败')
  } finally {
    loading.value = false
  }
}

function onPage(page: number) {
  load(page)
}

onMounted(() => load(1))
</script>

<template>
  <n-card title="执行记录">
    <template #header-extra><n-button :loading="loading" @click="load(pagination.page)">刷新</n-button></template>
    <n-alert type="info" :show-icon="false" style="margin-bottom: 16px">页面显示、服务端接收、送达与已读分别记录。当前页面执行器尚未接入服务端回执，不会据页面文字标记送达。“待核实”的消息不会自动重发。</n-alert>
    <n-data-table
      remote
      :columns="columns"
      :data="rows"
      :loading="loading"
      :bordered="false"
      :pagination="pagination"
      :scroll-x="700"
      @update:page="onPage"
    />
  </n-card>
</template>
