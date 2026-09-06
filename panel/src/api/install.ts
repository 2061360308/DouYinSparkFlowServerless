/** 管理员安装 API：使用现有会话 Cookie 和 CSRF 保护。 */
import { http } from './console.http'

export interface InstallCredentials {
  accessKeyId: string
  accessKeySecret: string
}

export interface DeployRequest {
  region: string
  stackName: string
  credentials: InstallCredentials
  parameters: Record<string, string>
}

export type StackStatus = 'CREATE_IN_PROGRESS' | 'CREATE_COMPLETE' | 'CREATE_FAILED'

export interface StackEvent {
  time: string
  logicalResourceId: string
  resourceType: string
  status: string
  statusReason?: string
}

export interface StackOutputs {
  /** Web 触发器公网访问地址。 */
  TriggerUrlInternet?: string
  /** Web 触发器内网访问地址。 */
  TriggerUrlIntranet?: string
  /** 浏览器函数名称。 */
  FunctionName?: string
  /** EventBridge 事件总线名称。 */
  EventBusName?: string
  /** 续火任务执行器函数名称。 */
  TaskFunctionName?: string
  /** 续火任务执行器 HTTP 触发器公网地址。 */
  TaskTriggerUrlInternet?: string
  /** 定时调度规则名称。 */
  ScheduleRuleName?: string
  /** 定时调度规则 ARN。 */
  ScheduleRuleARN?: string
  /** EventBridge API 端点名称。 */
  ApiDestinationName?: string
  /** EventBridge 连接配置名称。 */
  ConnectionName?: string
}

export interface DeployStatus {
  stackId: string
  status: StackStatus
  rawStatus?: string
  statusReason?: string
  events: StackEvent[]
  outputs?: StackOutputs
}

export interface DeployHandle {
  stackId: string
}


export async function deployStack(request: DeployRequest): Promise<DeployHandle> {
  return http.post<DeployHandle>('/api/install/deploy', request)
}

/** 单次查询并保存当前资源栈状态；后端持久化记录支持刷新恢复。 */
export async function getDeployStatus(_stackId: string): Promise<DeployStatus> {
  return http.post<DeployStatus>('/api/install/refresh')
}

export const repairInstallCredentials = (credentials: InstallCredentials, confirmation: string) =>
  http.post<DeployStatus>('/api/install/credentials', { credentials, confirmation })
export const cleanupInstallation = (confirmation: string) =>
  http.post<DeployStatus>('/api/install/cleanup', { confirmation })
export const resetInstallation = (confirmation: string) =>
  http.post<{ ok: boolean }>('/api/install/reset', { confirmation })
