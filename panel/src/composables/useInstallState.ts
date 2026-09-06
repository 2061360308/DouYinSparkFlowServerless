/** 安装状态只从后端读取，不再信任历史 localStorage 的演示标记。 */
import { http } from '../api/console.http'
import type { DeployStatus } from '../api/install'

export interface InstallStatus {
  mode: 'local' | 'cloud'
  installed: boolean
  needsInstall: boolean
  canDeploy: boolean
  missingEnv: string[]
  deployment: DeployStatus | null
}

export function getInstallStatus(): Promise<InstallStatus> {
  return http.get<InstallStatus>('/api/install/status')
}
