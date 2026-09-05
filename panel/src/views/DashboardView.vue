<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NGi,
  NGrid,
  NSpin,
  NStatistic,
  NTag,
  useMessage,
} from 'naive-ui'

import { dashboardApi, type DashboardData } from '../api/console'
import { formatDateTime, RUN_STATUS_LABEL, RUN_STATUS_TYPE } from '../utils/format'

const message = useMessage()
const loading = ref(true)
const data = ref<DashboardData | null>(null)

async function load() {
  loading.value = true
  try {
    data.value = await dashboardApi.get()
  } catch {
    message.error('加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <n-spin :show="loading">
    <div v-if="data" class="dash">
      <n-grid cols="2 s:4" responsive="screen" :x-gap="14" :y-gap="14">
        <n-gi>
          <n-card><n-statistic label="累计执行" :value="data.platform_status.total" /></n-card>
        </n-gi>
        <n-gi>
          <n-card><n-statistic label="成功" :value="data.platform_status.success" /></n-card>
        </n-gi>
        <n-gi>
          <n-card><n-statistic label="待执行" :value="data.platform_status.pending" /></n-card>
        </n-gi>
        <n-gi>
          <n-card><n-statistic label="失败" :value="data.platform_status.failed" /></n-card>
        </n-gi>
      </n-grid>

      <n-grid cols="1 m:2" responsive="screen" :x-gap="14" :y-gap="14" class="section">
        <n-gi>
          <n-card title="今日任务">
            <template #header-extra>
              <n-button text type="primary" @click="$router.push({ name: 'tasks' })">管理</n-button>
            </template>
            <n-empty v-if="data.tasks.length === 0" description="还没有续火任务" />
            <div v-else class="list">
              <div v-for="t in data.tasks" :key="t.id" class="row">
                <div class="row-main">
                  <span class="time">{{ t.send_time }}</span>
                  <span class="name">{{ t.target_name }}</span>
                </div>
                <div class="row-side">
                  <n-tag size="small" :type="t.enabled ? 'success' : 'default'" :bordered="false">
                    {{ t.enabled ? '启用' : '暂停' }}
                  </n-tag>
                  <span class="next">{{ formatDateTime(t.next_run_at) }}</span>
                </div>
              </div>
            </div>
          </n-card>
        </n-gi>
        <n-gi>
          <n-card title="最近执行">
            <template #header-extra>
              <n-button text type="primary" @click="$router.push({ name: 'runs' })">查看全部</n-button>
            </template>
            <n-empty v-if="data.recent_runs.length === 0" description="暂无执行记录" />
            <div v-else class="list">
              <div v-for="r in data.recent_runs" :key="r.id" class="row">
                <div class="row-main">
                  <span class="name">{{ r.target_name ?? '—' }}</span>
                </div>
                <div class="row-side">
                  <n-tag size="small" :type="RUN_STATUS_TYPE[r.status] ?? 'default'" :bordered="false">
                    {{ RUN_STATUS_LABEL[r.status] ?? r.status }}
                  </n-tag>
                  <span class="next">{{ formatDateTime(r.scheduled_for) }}</span>
                </div>
              </div>
            </div>
          </n-card>
        </n-gi>
      </n-grid>
    </div>
  </n-spin>
</template>

<style scoped>
.dash {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.section {
  margin-top: 2px;
}
.list {
  display: flex;
  flex-direction: column;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 2px;
  border-bottom: 1px solid rgba(128, 128, 128, 0.14);
}
.row:last-child {
  border-bottom: none;
}
.row-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}
.time {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #aa3bff;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-side {
  display: flex;
  align-items: center;
  gap: 10px;
}
.next {
  font-size: 12px;
  opacity: 0.6;
}
</style>
