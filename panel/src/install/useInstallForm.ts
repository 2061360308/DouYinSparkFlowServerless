/**
 * 引导安装向导的共享状态（provide/inject）。
 *
 * InstallWizard 调用 `createInstallStore()` 创建并注入；各步骤组件用
 * `useInstallStore()` 取用。状态含：只读固定项、用户输入项、以及部署运行时状态。
 */

import { inject, provide, reactive, type InjectionKey } from 'vue'

import { DEFAULT_SPEC, REGION, STACK_NAME, type FunctionSpec } from './fields'
import type { StackEvent, StackOutputs, StackStatus } from '../api/install'

export type DeployPhase = 'idle' | 'deploying' | 'success' | 'error'

export interface DeployRuntime {
  phase: DeployPhase
  stackId: string
  status: StackStatus | ''
  rawStatus: string
  statusReason: string
  events: StackEvent[]
  outputs: StackOutputs | null
  error: string
}

export interface InstallStore {
  /** 只读固定：地域。 */
  region: string
  /** 只读固定：资源栈名。 */
  stackName: string
  /** 用户输入：调用 ROS 的访问凭证。 */
  credentials: { accessKeyId: string; accessKeySecret: string }
  /** 用户输入：函数规格。 */
  spec: FunctionSpec
  /** 部署运行时状态。 */
  deploy: DeployRuntime
}

const InstallKey: InjectionKey<InstallStore> = Symbol('install-store')

function freshDeploy(): DeployRuntime {
  return {
    phase: 'idle',
    stackId: '',
    status: '',
    rawStatus: '',
    statusReason: '',
    events: [],
    outputs: null,
    error: '',
  }
}

/** 创建并注入安装向导状态（在向导根组件调用一次）。 */
export function createInstallStore(): InstallStore {
  const store = reactive<InstallStore>({
    region: REGION,
    stackName: STACK_NAME,
    credentials: { accessKeyId: '', accessKeySecret: '' },
    spec: { ...DEFAULT_SPEC },
    deploy: freshDeploy(),
  })
  provide(InstallKey, store)
  return store
}

/** 取用已注入的安装向导状态。 */
export function useInstallStore(): InstallStore {
  const store = inject(InstallKey)
  if (!store) {
    throw new Error('InstallStore 未提供：请在 InstallWizard 内使用 useInstallStore()')
  }
  return store
}

/** 重置部署运行时状态（用于重试）。 */
export function resetDeploy(store: InstallStore): void {
  Object.assign(store.deploy, freshDeploy())
}
