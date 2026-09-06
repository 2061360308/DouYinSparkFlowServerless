/**
 * 引导安装字段定义（单一事实来源）。
 *
 * 字段名与 `aliyunFC/install/ros-template.yaml` 的 Parameters 一一对应；
 * 后端 create_stack 只需提交被改动项，未指定项自动沿用模板 Default。
 *
 * 本期收敛：
 * - Region / StackName：只读固定；
 * - NamePrefix / FunctionName / ImageUrl / ContainerPort / TriggerName / TriggerAuthType /
 *   TaskFunctionName / TaskImageUrl / TaskContainerPort / TaskTriggerName / EventBusName /
 *   ApiDestinationName / ConnectionName / RuleName：定死（不在 UI 暴露）；
 * - 会话亲和 / 健康检查 / EventBridge 参数：不在 UI，沿用模板内置默认；
 * - 用户可编辑：AK/SK + 浏览器函数规格（Cpu / MemorySize / DiskSize / FunctionTimeout）+
 *   任务执行器函数规格（TaskCpu / TaskMemorySize / TaskFunctionTimeout）。
 */

// —— 地域与资源栈（只读固定）——
export const REGION = 'cn-hangzhou'
export const STACK_NAME = 'DouyinSpark'

// —— 定死的模板参数（不在 UI 暴露）——
// 说明：ImageUrl / TaskImageUrl 均锁定在 cn-hangzhou，故 Region 亦固定。
export const FIXED_PARAMETERS = {
  NamePrefix: 'DouyinSpark',
  FunctionName: 'DYSparkCloakBrowser',
  ImageUrl:
    'crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/cloakbrowser-serverless:latest',
  ContainerPort: '9000',
  TriggerName: 'webTrigger',
  TriggerAuthType: 'anonymous',
  TaskFunctionName: 'DYSparkTaskRunner',
  TaskImageUrl:
    'crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/douyin_spark_runner:latest',
  TaskContainerPort: '9000',
  TaskTriggerName: 'taskTrigger',
  EventBusName: 'DouyinSpark-bus',
  ApiDestinationName: 'DouyinSpark-fc-dest',
  ConnectionName: 'DouyinSpark-fc-conn',
  RuleName: 'DouyinSpark-schedule',
} as const

// —— 函数规格（用户可编辑）——
export interface FunctionSpec {
  Cpu: number
  MemorySize: number
  DiskSize: number
  FunctionTimeout: number
  TaskCpu: number
  TaskMemorySize: number
  TaskFunctionTimeout: number
}

export const DEFAULT_SPEC: FunctionSpec = {
  Cpu: 1,
  MemorySize: 1536,
  DiskSize: 512,
  FunctionTimeout: 600,
  TaskCpu: 0.5,
  TaskMemorySize: 512,
  TaskFunctionTimeout: 300,
}

// —— 规格约束（阿里云 FC3 标准）——
export const CPU_MIN = 0.05
export const CPU_MAX = 16
export const CPU_STEP = 0.05
export const MEMORY_STEP = 64 // 内存必须为 64MB 的倍数
export const MEMORY_FLOOR = 1536 // 浏览器函数业务下限 1.5GB
export const TASK_MEMORY_FLOOR = 128 // 任务执行器函数内存下限
export const MEMORY_RATIO_MIN = 1024 // 每 vCPU 最少 1GB
export const MEMORY_RATIO_MAX = 4096 // 每 vCPU 最多 4GB
export const TIMEOUT_MIN = 1
export const TIMEOUT_MAX = 86400
export const DISK_OPTIONS = [512, 10240] as const

/**
 * 依据当前 Cpu 计算内存下限/上限。
 * 规则：vCPU:内存(GB) = 1:1 ~ 1:4，内存为 64MB 的倍数，且不低于指定下限。
 */
export function memoryBounds(
  cpu: number,
  floor = MEMORY_FLOOR,
): { min: number; max: number } {
  const safeCpu = Number.isFinite(cpu) && cpu > 0 ? cpu : CPU_MIN
  const rawMin = Math.max(floor, safeCpu * MEMORY_RATIO_MIN)
  const min = Math.ceil(rawMin / MEMORY_STEP) * MEMORY_STEP
  const max = Math.floor((safeCpu * MEMORY_RATIO_MAX) / MEMORY_STEP) * MEMORY_STEP
  return { min: Math.max(min, floor), max: Math.max(min, max) }
}

/** 将内存夹取到当前 Cpu 允许的区间，并对齐到 64MB 倍数。 */
export function clampMemory(cpu: number, memory: number, floor = MEMORY_FLOOR): number {
  const { min, max } = memoryBounds(cpu, floor)
  const aligned = Math.round(memory / MEMORY_STEP) * MEMORY_STEP
  return Math.min(max, Math.max(min, aligned))
}

/**
 * 组装提交给后端（ROS create_stack）的模板参数表。
 * 固定项 + 用户函数规格，全部转为字符串（ROS ParameterValue 要求字符串）。
 */
export function buildParameters(spec: FunctionSpec): Record<string, string> {
  return {
    ...FIXED_PARAMETERS,
    Cpu: String(spec.Cpu),
    MemorySize: String(spec.MemorySize),
    DiskSize: String(spec.DiskSize),
    FunctionTimeout: String(spec.FunctionTimeout),
    TaskCpu: String(spec.TaskCpu),
    TaskMemorySize: String(spec.TaskMemorySize),
    TaskFunctionTimeout: String(spec.TaskFunctionTimeout),
  }
}
