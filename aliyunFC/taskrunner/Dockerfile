# =============================================================================
# 续火任务执行器（FC3 自定义容器「事件函数」）
#
# 作用：被 EventBridge 定时事件源触发 → 取 task_id → 调 core.task.run.run_task。
# 浏览器在远端（cloakbrowser），本镜像只做编排：Playwright connect_over_cdp 连远程
# 浏览器发送。故规格可很小，且**不需要 chromium 二进制**（playwright wheel 自带
# node driver 即可 connect_over_cdp）。
#
# 数据一律经 FastAPI 内部接口（/api/internal/*）取用与回写，不直连数据库；
# 因此镜像也**不需要** tortoise/argon2/cryptography 等后端依赖，只装 playwright + httpx。
#
# 构建上下文 = 仓库根（需 COPY core/）：
#   docker build -f aliyunFC/taskrunner/Dockerfile -t <img> .
# =============================================================================
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG IMAGE_VERSION=0.0.0-dev
LABEL org.opencontainers.image.title="douyinspark-taskrunner" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="续火计划任务执行器(FC3 事件函数): connect_over_cdp 驱动远程浏览器, 经内部 API 取数"

# playwright 自带的 node driver 运行需要少量系统库（connect_over_cdp 不下载浏览器）
RUN apt-get update && apt-get install -y --no-install-recommends \
       ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# 仅需 playwright(客户端, 不装 chromium) + httpx
RUN pip install --no-cache-dir "playwright==1.56.0" "httpx==0.28.1"

WORKDIR /app
COPY core/ ./core/
COPY aliyunFC/taskrunner/invoke_server.py ./invoke_server.py
COPY aliyunFC/taskrunner/VERSION ./VERSION

# FC 自定义容器需 HTTP 服务监听 0.0.0.0:9000（与 CustomContainerConfig.Port 一致）
ENV FC_SERVER_PORT=9000 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    IMAGE_VERSION=${IMAGE_VERSION}
EXPOSE 9000

CMD ["python", "invoke_server.py"]
