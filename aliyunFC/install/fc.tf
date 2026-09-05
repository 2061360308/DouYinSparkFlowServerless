# =============================================================================
# RAM 角色: FC 服务角色 (fc.aliyuncs.com 承担)
# 用于访问 SLS 日志、ECS 弹性网卡(VPC 模式)等
# =============================================================================
resource "alicloud_ram_role" "fc_service_role" {
  role_name                   = var.role_name
  description                 = "FC service role for cloakbrowser"
  assume_role_policy_document = <<EOF
{
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Effect": "Allow",
      "Principal": {
        "Service": [
          "fc.aliyuncs.com"
        ]
      }
    }
  ],
  "Version": "1"
}
EOF
}

resource "alicloud_ram_role_policy_attachment" "fc_log_policy" {
  role_name   = alicloud_ram_role.fc_service_role.role_name
  policy_name = "AliyunLogFullAccess"
  policy_type = "System"
}

resource "alicloud_ram_role_policy_attachment" "fc_eni_policy" {
  role_name   = alicloud_ram_role.fc_service_role.role_name
  policy_name = "AliyunECSNetworkInterfaceManagementAccess"
  policy_type = "System"
}

# =============================================================================
# FC3 函数 (自定义容器) + HTTP(web) 触发器
# =============================================================================
resource "alicloud_fcv3_function" "function" {
  function_name         = var.function_name
  description           = "CloakBrowser stealth Chromium remote debugging + websockets proxy"
  runtime               = "custom-container"
  handler               = var.handler
  cpu                   = var.cpu
  memory_size           = var.memory_size
  disk_size             = var.disk_size
  timeout               = var.function_timeout
  instance_concurrency  = var.instance_concurrency
  internet_access       = var.internet_access
  role                  = local.role_arn
  environment_variables = var.environment_variables

  session_affinity        = "HEADER_FIELD"
  session_affinity_config = jsonencode(local.session_affinity_config)

  custom_container_config {
    image      = var.image_url
    port       = var.container_port
    command    = []
    entrypoint = []

    health_check_config {
      http_get_url          = var.health_check_url
      initial_delay_seconds = var.health_initial_delay_seconds
      period_seconds        = var.health_period_seconds
      timeout_seconds       = var.health_timeout_seconds
      success_threshold     = 1
      failure_threshold     = 3
    }
  }

  vpc_config {
    vpc_id            = alicloud_vpc.vpc.id
    vswitch_ids       = [alicloud_vswitch.vswitch.id]
    security_group_id = alicloud_security_group.sg.id
  }

  log_config {
    log_begin_rule = "None"
  }

  tags = local.tags

  depends_on = [
    alicloud_ram_role_policy_attachment.fc_log_policy,
    alicloud_ram_role_policy_attachment.fc_eni_policy,
  ]
}

resource "alicloud_fcv3_trigger" "web_trigger" {
  function_name = alicloud_fcv3_function.function.function_name
  trigger_name  = var.trigger_name
  trigger_type  = "http"
  qualifier     = "LATEST"
  description   = "cloakbrowser web trigger"
  trigger_config = var.trigger_auth_type == "anonymous" ? jsonencode({
    authType = "anonymous"
    methods  = ["GET", "POST", "PUT", "DELETE", "HEAD"]
    }) : jsonencode({
    authType = "function"
    methods  = ["GET", "POST", "PUT", "DELETE", "HEAD"]
  })

  depends_on = [alicloud_fcv3_function.function]
}