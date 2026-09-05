"""install: 一键部署包 (ROS 资源编排)。

- ros-template.yaml: 单文件 ROS 模板 (VPC/NAT/EIP/RAM/FC3 自定义容器函数 + Web 触发器)
- ros_client.py: ROS OpenAPI 客户端库, 供后端模块创建资源栈/轮询状态/取触发器地址
"""

from install.ros_client import (
    RosStackClient,
    RosStackError,
    StackFailedError,
    StackWaitTimeoutError,
)

__all__ = [
    "RosStackClient",
    "RosStackError",
    "StackFailedError",
    "StackWaitTimeoutError",
]