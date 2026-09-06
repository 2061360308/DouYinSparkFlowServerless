<script setup lang="ts">
import { h, onMounted, ref } from 'vue'
import { NCard, NDataTable, NTag, useMessage, type DataTableColumns } from 'naive-ui'

import { runApi, type RunItem } from '../api/console'
import { formatDateTime, RUN_STATUS_LABEL, RUN_STATUS_TYPE } from '../utils/format'

const message = useMessage()
const rows = ref<RunItem[]>([])
const loading = ref(true)
const showOwner = ref(false)
const pagination = ref({ page: 1, pageCount: 1, pageSize: 6 })

const columns = ref<DataTableColumns<RunItem>>([])

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
    <n-data-table
      remote
      :columns="columns"
      :data="rows"
      :loading="loading"
      :bordered="false"
      :pagination="pagination"
      scroll-x="auto"
      @update:page="onPage"
    />
  </n-card>
</template>
