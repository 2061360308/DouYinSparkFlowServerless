/**
 * 安装部署 API 客户端。
 *
 * 当前为前端 mock 实现（本期只做前端，不接后端）。类型与方法契约对齐后端未来
 * 对 `aliyunFC/install/ros_client.py` 的封装，届时仅替换本文件的实现即可：
 *   deployStack     ↔ RosStackClient.create_stack
 *   getDeployStatus ↔ RosStackClient.get_stack_status / wait_stack_complete + get_stack_outputs
 */

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
  /** 固定公网出口 IP（EIP 地址，模板输出 EipIpAddress）。 */
  EipIpAddress?: string
  /** Web 触发器公网访问地址。 */
  TriggerUrlInternet?: string
  /** Web 触发器内网访问地址。 */
  TriggerUrlIntranet?: string
  /** 函数名称。 */
  FunctionName?: string
}

export interface DeployStatus {
  stackId: string
  status: StackStatus
  statusReason?: string
  events: StackEvent[]
  outputs?: StackOutputs
}

export interface DeployHandle {
  stackId: string
}

// ---------------------------------------------------------------------------
// 以下为 mock：用一条按时间推进的资源创建时间线模拟 ROS 资源栈创建过程。
// ---------------------------------------------------------------------------

interface MockRun {
  request: DeployRequest
  startedAt: number
}

const runs = new Map<string, MockRun>()

/** 资源创建阶段（顺序与 ros-template.yaml 的资源依赖大致一致）。 */
const STAGES: ReadonlyArray<{ id: string; type: string }> = [
  { id: 'Vpc', type: 'ALIYUN::ECS::VPC' },
  { id: 'VSwitch', type: 'ALIYUN::ECS::VSwitch' },
  { id: 'SecurityGroup', type: 'ALIYUN::ECS::SecurityGroup' },
  { id: 'NatGateway', type: 'ALIYUN::VPC::NatGateway' },
  { id: 'Eip', type: 'ALIYUN::VPC::EIP' },
  { id: 'SnatEntry', type: 'ALIYUN::VPC::SnatEntry' },
  { id: 'Role', type: 'ALIYUN::RAM::Role' },
  { id: 'Function', type: 'ALIYUN::FC3::Function' },
  { id: 'WebTrigger', type: 'ALIYUN::FC3::Trigger' },
]

/** 资源阶段总数（供前端计算进度百分比）。 */
export const TOTAL_RESOURCE_STAGES = STAGES.length

const STAGE_MS = 1500 // 每个资源阶段的模拟耗时

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 由 stackId 派生一个稳定的伪公网 IP（仅用于 mock 展示）。 */
function mockPublicIp(seed: string): string {
  let h = 0
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) >>> 0
  }
  const byte = (n: number) => (h >>> (n * 8)) & 0xff
  return `47.${byte(0)}.${byte(1)}.${(byte(2) % 254) + 1}`
}

/** 发起创建资源栈，同步返回 stackId（对应 create_stack）。 */
export async function deployStack(request: DeployRequest): Promise<DeployHandle> {
  await delay(600)
  const stackId = `stack-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`
  runs.set(stackId, { request, startedAt: Date.now() })
  return { stackId }
}

/** 查询资源栈状态与事件；创建完成后返回 outputs（对应 get_stack_status + get_stack_outputs）。 */
export async function getDeployStatus(stackId: string): Promise<DeployStatus> {
  await delay(400)
  const run = runs.get(stackId)
  if (!run) {
    return {
      stackId,
      status: 'CREATE_FAILED',
      statusReason: '资源栈不存在或已过期',
      events: [],
    }
  }

  const elapsed = Date.now() - run.startedAt
  const done = Math.min(STAGES.length, Math.floor(elapsed / STAGE_MS))
  const events: StackEvent[] = STAGES.slice(0, done).map((stage, index) => ({
    time: new Date(run.startedAt + index * STAGE_MS).toISOString(),
    logicalResourceId: stage.id,
    resourceType: stage.type,
    status: 'CREATE_COMPLETE',
  }))

  if (done < STAGES.length) {
    return { stackId, status: 'CREATE_IN_PROGRESS', events }
  }

  const params = run.request.parameters
  const functionName = params.FunctionName || 'DYSparkCloakBrowser'
  const outputs: StackOutputs = {
    EipIpAddress: mockPublicIp(stackId),
    TriggerUrlInternet: `https://${functionName.toLowerCase()}-mockuid.${run.request.region}.fcapp.run`,
    TriggerUrlIntranet: `https://${functionName.toLowerCase()}-mockuid.${run.request.region}-internal.fcapp.run`,
    FunctionName: functionName,
  }
  return { stackId, status: 'CREATE_COMPLETE', events, outputs }
}
