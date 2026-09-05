# =============================================================================
# VPC 网络: VPC + 交换机 + 安全组
# =============================================================================
resource "alicloud_vpc" "vpc" {
  vpc_name   = "${local.name_prefix}-vpc"
  cidr_block = var.vpc_cidr_block
  tags       = local.tags
}

resource "alicloud_vswitch" "vswitch" {
  vswitch_name = "${local.name_prefix}-vswitch"
  cidr_block   = var.vswitch_cidr_block
  zone_id      = var.zone_id
  vpc_id       = alicloud_vpc.vpc.id
  tags         = local.tags
}

resource "alicloud_security_group" "sg" {
  security_group_name = "${local.name_prefix}-sg"
  description         = "cloakbrowser FC3 function security group"
  vpc_id              = alicloud_vpc.vpc.id
  tags                = local.tags
}

# FC 容器需访问公网(拉取镜像/对外访问), 放行所有出方向
resource "alicloud_security_group_rule" "egress_all" {
  type              = "egress"
  ip_protocol       = "all"
  nic_type          = "intranet"
  policy            = "accept"
  priority          = 1
  security_group_id = alicloud_security_group.sg.id
  cidr_ip           = "0.0.0.0/0"
}

# =============================================================================
# 公网: NAT 网关 + EIP + 关联 + SNAT (固定公网出口 IP)
# =============================================================================
resource "alicloud_nat_gateway" "nat" {
  vpc_id               = alicloud_vpc.vpc.id
  nat_gateway_name     = "${local.name_prefix}-nat"
  description          = "cloakbrowser fixed egress"
  payment_type         = var.nat_payment_type
  nat_type             = var.nat_type
  vswitch_id           = alicloud_vswitch.vswitch.id
  internet_charge_type = var.nat_internet_charge_type
  tags                 = local.tags
}

resource "alicloud_eip_address" "eip" {
  internet_charge_type = var.eip_internet_charge_type
  bandwidth            = var.eip_bandwidth
  payment_type         = "PayAsYouGo"
  address_name         = "${local.name_prefix}-eip"
  isp                  = var.eip_isp
}

resource "alicloud_eip_association" "nat_bind" {
  allocation_id = alicloud_eip_address.eip.id
  instance_id   = alicloud_nat_gateway.nat.id
  instance_type = "NAT"
}

resource "alicloud_snat_entry" "snat" {
  snat_table_id     = alicloud_nat_gateway.nat.snat_table_ids
  source_vswitch_id = alicloud_vswitch.vswitch.id
  snat_ip           = alicloud_eip_address.eip.ip_address
  snat_entry_name   = "${local.name_prefix}-snat"
}