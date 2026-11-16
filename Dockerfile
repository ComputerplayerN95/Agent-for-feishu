# ---- 构建阶段 ----
FROM python:3.12-slim AS builder

WORKDIR /build

# 先只拷依赖声明，利用 Docker 层缓存
COPY pyproject.toml ./
COPY agentd/ ./agentd/

# 构建 wheel（不装进构建阶段，只产出产物）
RUN pip install --no-cache-dir build \
    && python -m build --wheel

# ---- 运行阶段 ----
FROM python:3.12-slim

# 创建非 root 用户，uid/gid 都是 1000，与契约一致
RUN groupadd -g 1000 agent \
    && useradd -u 1000 -g 1000 -m -s /usr/sbin/nologin agent

WORKDIR /app

# 只把 wheel 从构建阶段拷过来
COPY --from=builder /build/dist/*.whl ./

# 安装 wheel 后删掉，保持镜像干净
RUN pip install --no-cache-dir *.whl \
    && rm -f *.whl

# 切换为非 root 用户
USER 1000:1000

EXPOSE 8080

# 契约要求：入口是 agentd，默认子命令 serve
ENTRYPOINT ["agentd"]
CMD ["serve"]
