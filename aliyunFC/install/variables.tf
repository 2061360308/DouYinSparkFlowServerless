# =============================================================================
# 全局参数
# =============================================================================
variable "region" {
  type        = string
  default     = "cn-hangzhou"
  description = "资源地域(弹性公网IP出口/函数计算所在地区)"
}

variable "name_prefix" {
  type        = string
  default     = "cloakbrowser"
  description = "VPC/NAT/EIP/安全组等资源名称前缀"
}

variable "zone_id" {
  type        = string
  default     = "cn-hangzhou-b"
  description = "交换机可用区"
}

variable "vpc_cidr_block" {
  type        = string
  default     = "172.16.0.0/16"
  description = "VPC CIDR"
}

variable "vswitch_cidr_block" {
  type        = string
  default     = "172.16.0.0/24"
  description = "交换机 CIDR"
}

# =============================================================================
# NAT / EIP 参数
# =============================================================================
variable "nat_type" {
  type        = string
  default     = "Enhanced"
  description = "NAT 网关类型: Enhanced / Normal"
}

variable "nat_payment_type" {
  type        = string
  default     = "PayAsYouGo"
  description = "NAT 网关付费方式"
}

variable "nat_internet_charge_type" {
  type        = string
  default     = "PayByLcu"
  description = "NAT 网关计费方式: PayByLcu(按量)/ PayBySpec(按规格)"
}

variable "eip_bandwidth" {
  type        = number
  default     = 5
  description = "EIP 带宽(Mbps)"
}

variable "eip_internet_charge_type" {
  type        = string
  default     = "PayByTraffic"
  description = "EIP 计费方式: PayByTraffic(按流量)/ PayByBandwidth(按带宽)"
}

variable "eip_isp" {
  type        = string
  default     = "BGP"
  description = "EIP 线路类型"
}

# =============================================================================
# RAM 角色
# =============================================================================
variable "role_name" {
  type        = string
  default     = "cloakbrowser-fc3-role"
  description = "FC 服务 RAM 角色名"
}

# =============================================================================
# FC3 函数参数
# =============================================================================
variable "function_name" {
  type        = string
  default     = "cloakbrowser"
  description = "函数名称"
}

variable "handler" {
  type        = string
  default     = "index.handler"
  description = "函数入口(custom-container 下为占位, 实际由容器入口决定)"
}

variable "image_url" {
  type        = string
  default     = "crpi-yagm0mg4gyj902wq.cn-hangzhou.personal.cr.aliyuncs.com/oilu/cloakbrowser-serverless:latest"
  description = "ACR 自定义容器镜像地址"
}

variable "cpu" {
  type        = number
  default     = 1
  description = "CPU(vCPU)"
}

variable "memory_size" {
  type        = number
  default     = 1536
  description = "内存(MB)"
}

variable "disk_size" {
  type        = number
  default     = 10240
  description = "磁盘(MB)"
}

variable "function_timeout" {
  type        = number
  default     = 600
  description = "容器最大执行时间(秒)"
}

variable "instance_concurrency" {
  type        = number
  default     = 1
  description = "单实例处理并发度"
}

variable "internet_access" {
  type        = bool
  default     = true
  description = "是否允许函数访问公网"
}

variable "environment_variables" {
  type        = map(string)
  default     = {}
  description = "环境变量"
}

variable "container_port" {
  type        = number
  default     = 9000
  description = "容器 HTTP 监听端口"
}

variable "trigger_name" {
  type        = string
  default     = "webTrigger"
  description = "Web 触发器名称"
}

variable "trigger_auth_type" {
  type        = string
  default     = "anonymous"
  description = "Web 触发器鉴权方式: anonymous(无需鉴权)/ function(需签名鉴权)"
}

# =============================================================================
# 会话亲和参数 (HeaderFieldSessionAffinityConfig)
# =============================================================================
variable "session_affinity_header_field_name" {
  type        = string
  default     = "sessionid"
  description = "会话亲和请求头名"
}

variable "session_ttl_seconds" {
  type        = number
  default     = 600
  description = "会话最长生命周期(秒)"
}

variable "session_idle_timeout_seconds" {
  type        = number
  default     = 30
  description = "会话空闲(无请求)等待时间(秒)"
}

variable "session_concurrency_per_instance" {
  type        = number
  default     = 1
  description = "单实例同时处理的最大 Session 数"
}

variable "disable_session_id_reuse" {
  type        = bool
  default     = false
  description = "Session 过期后是否拒绝复用(SessionID 重新计算)"
}

# =============================================================================
# 健康检查
# =============================================================================
variable "health_check_url" {
  type        = string
  default     = "/healthz"
  description = "自定义容器健康检查探测路径"
}

variable "health_initial_delay_seconds" {
  type        = number
  default     = 5
  description = "容器启动后延迟探测时间(秒)"
}

variable "health_period_seconds" {
  type        = number
  default     = 5
  description = "健康检查周期(秒)"
}

variable "health_timeout_seconds" {
  type        = number
  default     = 1
  description = "健康检查超时(秒)"
}