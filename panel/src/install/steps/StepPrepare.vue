<script setup lang="ts">
import { NAlert } from 'naive-ui'

import { FIXED_PARAMETERS, REGION, STACK_NAME } from '../fields'

const resources: Array<{ name: string; desc: string }> = [
  { name: 'VPC / 交换机 / 安全组', desc: '专用网络与子网，出网放行' },
  { name: 'NAT 网关（增强型）', desc: '执行 SNAT，将函数私网流量转出公网' },
  { name: '弹性公网 IP（EIP）', desc: '固定公网出口 IP，对外呈现的地址' },
  { name: 'RAM 服务角色', desc: 'FC 承担，挂载日志与网卡管理权限' },
  { name: 'FC3 自定义容器函数', desc: `${FIXED_PARAMETERS.FunctionName}，运行 cloakbrowser 镜像` },
  { name: 'Web(HTTP) 触发器', desc: '对外提供访问入口' },
]
</script>

<template>
  <div class="step-prepare">
    <p class="lead">
      本向导将在阿里云
      <b>{{ REGION }}</b>
      地域，以资源栈
      <b>{{ STACK_NAME }}</b>
      一键创建以下资源，用于部署 cloakbrowser serverless 浏览器函数：
    </p>

    <ul class="res-list">
      <li v-for="r in resources" :key="r.name">
        <span class="res-name">{{ r.name }}</span>
        <span class="res-desc">{{ r.desc }}</span>
      </li>
    </ul>

    <n-alert title="固定公网出口 IP 说明" type="success" :bordered="true" class="tip">
      函数出网被强制走 VPC → NAT → SNAT → EIP，对外呈现的固定公网 IP 即
      <b>弹性公网 IP（EIP）</b>
      的地址；NAT 网关只负责转发，最终出口 IP 由 EIP 决定。
    </n-alert>

    <n-alert title="计费提示" type="warning" :bordered="true" class="tip">
      NAT 网关（按 LCU 计费）与 EIP（默认 5 Mbps，按流量计费）会持续产生费用，删除资源栈即可一并销毁。
    </n-alert>

    <n-alert title="前置条件" type="info" :bordered="true" class="tip">
      <ul class="req-list">
        <li>阿里云账号已完成实名认证</li>
        <li>已开通函数计算 FC、专有网络 VPC、访问控制 RAM、NAT 网关等服务</li>
        <li>准备一对具备上述资源创建权限的 AccessKey（下一步填写）</li>
      </ul>
    </n-alert>
  </div>
</template>

<style scoped>
.step-prepare {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.lead {
  line-height: 1.7;
}
.res-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.res-list li {
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.24));
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.res-name {
  font-weight: 600;
}
.res-desc {
  font-size: 13px;
  opacity: 0.7;
}
.req-list {
  margin: 4px 0 0;
  padding-left: 18px;
  line-height: 1.8;
}
.tip :deep(b) {
  font-weight: 600;
}
</style>
