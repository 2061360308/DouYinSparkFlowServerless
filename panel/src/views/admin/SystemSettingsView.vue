<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NCheckbox,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NPageHeader,
  NSelect,
  NSpace,
  NSwitch,
  NText,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  CloudOutline,
  CubeOutline,
  DesktopOutline,
  FlashOutline,
  HelpCircleOutline,
  LinkOutline,
  PersonCircleOutline,
  WifiOutline,
} from '@vicons/ionicons5'

import { adminApi } from '../../api/console'

type FieldType = 'string' | 'password' | 'number' | 'boolean' | 'select' | 'json'

interface FieldMeta {
  key: string
  label: string
  type: FieldType
  description?: string
  options?: { label: string; value: string }[]
  min?: number
  max?: number
  step?: number
}

interface GroupMeta {
  key: string
  title: string
  icon: typeof CloudOutline
  fields: FieldMeta[]
}

const message = useMessage()
const router = useRouter()

const loading = ref(true)
const saving = ref(false)
const values = ref<Record<string, string>>({})
const configured = ref<Record<string, boolean>>({})
const clearSecrets = ref<string[]>([])
const installationCredentialsActive = ref(false)
const loaded = ref(false)

function markClear(key: string, checked: boolean) {
  clearSecrets.value = clearSecrets.value.filter((item) => item !== key)
  if (checked) {
    clearSecrets.value.push(key)
    values.value[key] = ''
  }
}

const groups = computed<GroupMeta[]>(() => [
  {
    key: 'browser',
    title: '浏览器运行时',
    icon: DesktopOutline,
    fields: [
      {
        key: 'browser_concurrency',
        label: '浏览器并发数',
        type: 'number',
        description: '同时可创建的远程浏览器实例数量',
        min: 1,
        max: 64,
        step: 1,
      },
    ],
  },
  {
    key: 'fc',
    title: '云函数连接',
    icon: CloudOutline,
    fields: [
      {
        key: 'fc_function_url',
        label: 'HTTP 触发器公网地址',
        type: 'string',
        description: '如 https://<fn>-<uid>.<region>.fcapp.run',
      },
      {
        key: 'fc_qualifier',
        label: '函数版本/别名',
        type: 'string',
        description: '调用云函数时使用的版本或别名，默认 LATEST',
      },
    ],
  },
  {
    key: 'account',
    title: '阿里云账号与角色',
    icon: PersonCircleOutline,
    fields: [
      {
        key: 'platform_access_key_id',
        label: '平台 AccessKey ID',
        type: 'password',
        description: 'AssumeRole 发起方的 AK',
      },
      {
        key: 'platform_access_key_secret',
        label: '平台 AccessKey Secret',
        type: 'password',
        description: 'AssumeRole 发起方的 SK',
      },
      {
        key: 'target_account_id',
        label: '目标账号主账号 ID',
        type: 'string',
        description: '资源实际部署到的阿里云主账号',
      },
      {
        key: 'assume_role_arn',
        label: 'AssumeRole ARN',
        type: 'string',
        description: '目标账号内信任平台账号的角色 ARN',
      },
      {
        key: 'role_session_name',
        label: 'Role Session Name',
        type: 'string',
        description: 'AssumeRole 会话名',
      },
      {
        key: 'region',
        label: '地域',
        type: 'string',
        description: 'FC 部署地域，如 cn-hangzhou',
      },
      {
        key: 'function_exec_role_arn',
        label: '函数执行角色 ARN',
        type: 'string',
        description: '留空则使用 FC 服务关联角色',
      },
      {
        key: 'auto_create_slr',
        label: '自动创建服务关联角色',
        type: 'boolean',
        description: '部署时是否自动创建 FC 服务关联角色',
      },
    ],
  },
  {
    key: 'network',
    title: '网络',
    icon: WifiOutline,
    fields: [
      {
        key: 'vpc_cidr',
        label: 'VPC 网段',
        type: 'string',
        description: '如 172.16.0.0/16',
      },
      {
        key: 'vswitch_cidr',
        label: '交换机网段',
        type: 'string',
        description: '如 172.16.0.0/20',
      },
      {
        key: 'zone_id',
        label: '可用区',
        type: 'string',
        description: '留空时自动选择',
      },
      {
        key: 'eip_bandwidth_mbps',
        label: 'EIP 带宽峰值 (Mbps)',
        type: 'number',
        description: '按流量计费上限',
        min: 1,
        max: 1000,
        step: 1,
      },
    ],
  },
  {
    key: 'function',
    title: '函数与镜像',
    icon: CubeOutline,
    fields: [
      {
        key: 'function_name',
        label: '函数名',
        type: 'string',
        description: '字母开头，1~64 位',
      },
      {
        key: 'image_url',
        label: '容器镜像地址',
        type: 'string',
        description: 'ACR 镜像完整地址',
      },
      {
        key: 'image_registry_username',
        label: '镜像仓库用户名',
        type: 'string',
        description: '公开镜像留空',
      },
      {
        key: 'image_registry_password',
        label: '镜像仓库密码',
        type: 'password',
        description: '公开镜像留空',
      },
      {
        key: 'container_port',
        label: '容器端口',
        type: 'number',
        description: '镜像内 HTTP Server 监听端口',
        min: 1,
        max: 65535,
        step: 1,
      },
      {
        key: 'cpu_vcores',
        label: 'CPU (vCPU)',
        type: 'number',
        description: '函数 CPU 核数',
        min: 0.05,
        max: 16,
        step: 0.05,
      },
      {
        key: 'memory_size_mb',
        label: '内存 (MB)',
        type: 'number',
        description: '64MB 倍数，与 CPU 比例 1:1~1:4',
        min: 128,
        max: 65536,
        step: 64,
      },
      {
        key: 'timeout_seconds',
        label: '函数超时 (秒)',
        type: 'number',
        description: '函数单次执行最大时间',
        min: 1,
        max: 86400,
        step: 1,
      },
      {
        key: 'disk_size_mb',
        label: '磁盘 (MB)',
        type: 'select',
        description: '512 或 10240',
        options: [
          { label: '512 MB', value: '512' },
          { label: '10240 MB', value: '10240' },
        ],
      },
    ],
  },
  {
    key: 'affinity',
    title: '会话亲和',
    icon: LinkOutline,
    fields: [
      {
        key: 'affinity_header_field_name',
        label: '亲和请求头名',
        type: 'string',
        description: '如 sessionid',
      },
      {
        key: 'session_concurrency_per_instance',
        label: '单实例 Session 数',
        type: 'number',
        description: '单个实例最多同时服务的 Session 数',
        min: 1,
        max: 200,
        step: 1,
      },
      {
        key: 'session_ttl_seconds',
        label: 'Session 生命周期 (秒)',
        type: 'number',
        description: 'Session 最长存活时间',
        min: 1,
        max: 21600,
        step: 1,
      },
      {
        key: 'session_idle_timeout_seconds',
        label: 'Session 空闲超时 (秒)',
        type: 'number',
        description: 'Session 空闲多久后回收',
        min: 0,
        max: 21600,
        step: 1,
      },
      {
        key: 'disable_session_id_reuse',
        label: '禁用 SessionID 复用',
        type: 'boolean',
        description: 'Session 过期后是否拒绝复用相同 ID',
      },
    ],
  },
  {
    key: 'trigger',
    title: '触发器',
    icon: FlashOutline,
    fields: [
      {
        key: 'trigger_name',
        label: 'HTTP 触发器名',
        type: 'string',
        description: '如 default-http',
      },
      {
        key: 'trigger_methods',
        label: '允许的 HTTP 方法',
        type: 'json',
        description: 'JSON 数组，如 ["GET", "POST"]',
      },
    ],
  },
])

function getFieldValue(key: string, type: FieldType): string | number | boolean | null {
  const raw = values.value[key] ?? ''
  if (type === 'boolean') return raw === 'true'
  if (type === 'number') {
    const n = Number(raw)
    return Number.isNaN(n) ? null : n
  }
  return raw
}

function setFieldValue(key: string, type: FieldType, value: string | number | boolean | null): void {
  if (value === null || value === undefined) {
    values.value[key] = ''
    return
  }
  if (type === 'boolean') {
    values.value[key] = value ? 'true' : 'false'
  } else {
    values.value[key] = String(value)
  }
}

async function load() {
  loading.value = true
  loaded.value = false
  try {
    const res = await adminApi.getSystemConfig()
    values.value = { ...res.values }
    configured.value = res.secret_configured
    installationCredentialsActive.value = res.installation_credentials_active
    clearSecrets.value = []
    loaded.value = true
  } catch {
    message.error('加载系统配置失败')
  } finally {
    loading.value = false
  }
}

function validate(): boolean {
  const jsonFields = groups.value.flatMap((g) => g.fields).filter((f) => f.type === 'json')
  for (const field of jsonFields) {
    const raw = values.value[field.key] ?? ''
    if (!raw.trim()) continue
    try {
      JSON.parse(raw)
    } catch {
      message.error(`「${field.label}」不是有效的 JSON`)
      return false
    }
  }
  return true
}

async function save() {
  if (!loaded.value || loading.value || saving.value) return
  if (!validate()) return
  saving.value = true
  try {
    await adminApi.updateSystemConfig({ ...values.value }, clearSecrets.value)
    for (const key of Object.keys(configured.value)) values.value[key] = ''
    message.success('配置已保存；已有云资源不会自动重新部署')
    await load()
  } catch {
    message.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="system-settings">
    <n-page-header title="系统设置" @back="router.push({ name: 'dashboard' })">
      <template #extra>
        <n-button type="primary" :disabled="!loaded || loading" :loading="saving" @click="save">保存配置</n-button>
      </template>
    </n-page-header>

    <n-spin :show="loading">
      <div class="settings-body">
        <n-alert type="info" style="margin-bottom: 16px">
          密钥仅显示是否已配置，留空保留原值。保存配置不会重新部署资源；修复调度配置后，请在任务页重试同步。
          <template v-if="installationCredentialsActive">当前运行优先使用安装向导保存的云凭据，此处平台 AK/SK 是备用配置，修改它们不会替换安装凭据。</template>
        </n-alert>
        <n-form :disabled="saving || loading" label-placement="top" require-mark-placement="right-hanging">
          <n-card
            v-for="group in groups"
            :key="group.key"
            :title="group.title"
            size="small"
            class="group-card"
          >
            <template #header-extra>
              <n-icon :component="group.icon" :size="18" class="group-icon" />
            </template>

            <n-grid cols="1 s:2 m:3" responsive="screen" :x-gap="16" :y-gap="12">
              <n-gi v-for="field in group.fields" :key="field.key">
                <n-form-item>
                  <template #label>
                    <span class="field-label">
                      {{ field.label }}
                      <n-tooltip v-if="field.description" trigger="hover">
                        <template #trigger>
                          <n-icon :component="HelpCircleOutline" :size="14" class="help-icon" />
                        </template>
                        {{ field.description }}
                      </n-tooltip>
                    </span>
                  </template>

                  <n-input
                    v-if="field.type === 'string'"
                    :value="String(getFieldValue(field.key, field.type))"
                    @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    :placeholder="field.description"
                  />

                  <n-input
                    v-else-if="field.type === 'password'"
                    type="password"
                    show-password-on="click"
                    :disabled="clearSecrets.includes(field.key) || saving || loading"
                    :value="String(getFieldValue(field.key, field.type))"
                    @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    :placeholder="configured[field.key] ? '已配置，留空保持不变' : '尚未配置'"
                  />

                  <n-input
                    v-else-if="field.type === 'json'"
                    type="textarea"
                    :rows="2"
                    :value="String(getFieldValue(field.key, field.type))"
                    @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    :placeholder="field.description"
                  />

                  <n-input-number
                    v-else-if="field.type === 'number'"
                    class="fill"
                    :value="Number(getFieldValue(field.key, field.type))"
                    @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    :min="field.min"
                    :max="field.max"
                    :step="field.step"
                    :placeholder="field.description"
                  />

                  <n-select
                    v-else-if="field.type === 'select'"
                    :value="String(getFieldValue(field.key, field.type))"
                    @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    :options="field.options"
                    :placeholder="field.description"
                  />

                  <n-space v-else-if="field.type === 'boolean'" align="center" style="height: 34px">
                    <n-switch
                      :value="Boolean(getFieldValue(field.key, field.type))"
                      @update:value="(v) => setFieldValue(field.key, field.type, v)"
                    />
                    <n-text depth="3">{{ field.description }}</n-text>
                  </n-space>
                  <n-checkbox v-if="field.type === 'password' && configured[field.key]"
                    :checked="clearSecrets.includes(field.key)"
                    @update:checked="(checked) => markClear(field.key, checked)"
                  >保存时清除</n-checkbox>
                </n-form-item>
              </n-gi>
            </n-grid>
          </n-card>
        </n-form>

        <n-space justify="end" class="footer-actions">
          <n-button @click="router.push({ name: 'dashboard' })">取消</n-button>
          <n-button type="primary" :disabled="!loaded || loading" :loading="saving" @click="save">保存配置</n-button>
        </n-space>
      </div>
    </n-spin>
  </div>
</template>

<style scoped>
.system-settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.settings-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.group-card {
  border-radius: 12px;
}
.group-card :deep(.n-card-header) {
  font-weight: 600;
}
.group-icon {
  color: #aa3bff;
  opacity: 0.8;
}
.field-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.help-icon {
  cursor: help;
  opacity: 0.55;
}
.help-icon:hover {
  opacity: 0.85;
}
.fill {
  width: 100%;
}
.footer-actions {
  padding: 8px 0 16px;
}
</style>
