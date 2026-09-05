provider "alicloud" {
  region = var.region
}

data "alicloud_account" "current" {}

locals {
  name_prefix = var.name_prefix
  role_arn    = alicloud_ram_role.fc_service_role.arn

  session_affinity_config = {
    headerFieldSessionAffinityConfig = {
      affinityHeaderFieldName       = var.session_affinity_header_field_name
      sessionTTLInSeconds           = var.session_ttl_seconds
      sessionIdleTimeoutInSeconds   = var.session_idle_timeout_seconds
      sessionConcurrencyPerInstance = var.session_concurrency_per_instance
      disableSessionIdReuse         = var.disable_session_id_reuse
    }
  }

  tags = {
    Service = "cloakbrowser"
  }
}