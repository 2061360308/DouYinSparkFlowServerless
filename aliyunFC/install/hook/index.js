async function preInit(inputObj) {
  console.log(`
  CloakBrowser Serverless (FC3 自定义容器)
  依赖服务:
    - 函数计算 FC : https://fc.console.aliyun.com/
    - 容器镜像服务 ACR : https://cr.console.aliyun.com/

  使用前请确认:
    - 已安装 Serverless Devs: npm i -g @serverless-devs/s
    - 已配置仓库密钥: s config add --AccessKeyID xxx --AccessKeySecret xxx -a default
    - ACR 镜像已存在且为公开/同账号可拉取
  `);
}

async function postInit(inputObj) {
  console.log(`
  ✨ 初始化完成!
  下一步:
    cd src
    s deploy                 # 创建/更新云函数
    s info                   # 查看函数与触发器地址
    s remove                 # 删除云函数
  `);
}

module.exports = {
  postInit,
  preInit
};