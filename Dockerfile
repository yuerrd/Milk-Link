# ── Milk-Link FastAPI Service ─────────────────────────────────────────────────
# 使用官方 uv 镜像（含 Python 3.11），避免手动安装 uv
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存（依赖不变则不重新安装）
COPY pyproject.toml uv.lock ./

# 安装生产依赖（跳过 dev 依赖，--frozen 确保与 uv.lock 完全一致）
RUN uv sync --frozen --no-dev

# 复制项目源码和迁移文件
COPY app/       ./app/
COPY alembic/   ./alembic/
COPY alembic.ini ./
COPY entrypoint.sh ./

RUN chmod +x entrypoint.sh

EXPOSE 8000

# 入口：先执行 DB 迁移，再启动服务
ENTRYPOINT ["./entrypoint.sh"]
