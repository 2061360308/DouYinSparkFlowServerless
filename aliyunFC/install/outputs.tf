# =============================================================================
# 输出
# =============================================================================

# 固定公网出口: EIP 实例 ID 与其公网地址
output "eip_id" {
  description = "固定公网出口 IP 的 EIP 实例 ID"
  value       = alicloud_eip_address.eip.id
}

output "eip_ip_address" {
  description = "固定公网出口公网 IP 地址"
  value       = alicloud_eip_address.eip.ip_address
}

output "nat_gateway_id" {
  description = "NAT 网关 ID"
  value       = alicloud_nat_gateway.nat.id
}

output "vpc_id" {
  description = "VPC ID"
  value       = alicloud_vpc.vpc.id
}

output "vswitch_id" {
  description = "交换机 ID"
  value       = alicloud_vswitch.vswitch.id
}

output "security_group_id" {
  description = "安全组 ID"
  value       = alicloud_security_group.sg.id
}

# 触发器公网访问地址
output "trigger_url_internet" {
  description = "Web 触发器公网访问地址"
  value       = alicloud_fcv3_trigger.web_trigger.http_trigger[0].url_internet
}

output "trigger_url_intranet" {
  description = "Web 触发器内网访问地址"
  value       = alicloud_fcv3_trigger.web_trigger.http_trigger[0].url_intranet
}

output "function_name" {
  description = "函数名称"
  value       = alicloud_fcv3_function.function.function_name
}