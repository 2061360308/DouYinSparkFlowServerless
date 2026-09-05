"""业务事件 handler（注册进 task.registry，供 task.run 按 event_category 回调）。

约定：``@handler("event_category")`` 装饰器登记；handler 内实现具体业务用例
（如「续火」：经 core 用例 → browser.acquire 申请浏览器 → 自动化发送 → 回写 db）。
task/ 保持通用、不依赖 core；执行入口在启动时 import 本包以填充注册表(组合根接线)。

本期暂无业务 handler（续火等执行面依赖常驻浏览器，后续接入）。
"""
