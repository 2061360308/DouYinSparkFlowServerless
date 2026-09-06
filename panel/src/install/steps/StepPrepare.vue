<script setup lang="ts">
import { NAlert } from 'naive-ui'

import { FIXED_PARAMETERS, REGION, STACK_NAME } from '../fields'

const resources: Array<{ name: string; desc: string }> = [
  { name: 'RAM 服务角色', desc: 'FC 承担，挂载日志访问权限' },
  { name: 'FC3 自定义容器函数', desc: `${FIXED_PARAMETERS.FunctionName}，运行 cloakbrowser 镜像` },
  { name: 'Web(HTTP) 触发器', desc: '对外提供 cloakbrowser 访问入口' },
  { name: '事件总线（EventBridge）', desc: `${FIXED_PARAMETERS.EventBusName}，供计划任务定时调度` },
  { name: '续火任务执行器函数', desc: `${FIXED_PARAMETERS.TaskFunctionName}，运行 taskrunner 镜像` },
  { name: '任务 HTTP 触发器', desc: 'EventBridge 经 Connection 调用任务函数' },
]
</script>

<template>
  <div class="step-prepare">
    <p class="lead">
      本向导将在阿里云
      <b>{{ REGION }}</b>
      地域，以资源栈
      <b>{{ STACK_NAME }}</b>
      一键创建以下资源，用于部署 cloakbrowser serverless 浏览器函数及续火任务执行器：
    </p>

    <ul class="res-list">
      <li v-for="r in resources" :key="r.name">
        <span class="res-name">{{ r.name }}</span>
        <span class="res-desc">{{ r.desc }}</span>
      </li>
    </ul>

    <n-alert title="公网访问说明" type="success" :bordered="true" class="tip">
      函数已开启"允许默认网卡访问公网"(
      <b>InternetAccess: true</b>
      )，可直接访问公网，无需创建 VPC / NAT / EIP；出网 IP 由函数计算平台动态分配，不固定。
    </n-alert>

    <n-alert title="计费提示" type="warning" :bordered="true" class="tip">
      函数计算 FC、EventBridge 等资源会按实际调用量持续产生费用，删除资源栈即可一并销毁。
    </n-alert>

    <n-alert title="前置条件" type="info" :bordered="true" class="tip">
      <ul class="req-list">
        <li>阿里云账号已完成实名认证</li>
        <li>已开通函数计算 FC、访问控制 RAM、事件总线 EventBridge 等服务</li>
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
