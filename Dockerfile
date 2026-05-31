# ==================== 阶段1: 构建前端 ====================
FROM node:20-alpine AS frontend-builder

# 设置工作目录
WORKDIR /frontend

# 复制前端依赖文件
COPY frontend/package*.json ./

# 安装所有依赖（包括开发依赖，构建时需要）
RUN npm ci

# 复制前端源码
COPY frontend/ ./

# 构建前端
RUN npm run generate

# ==================== 阶段2: 构建最终镜像 ====================
FROM python:3.11-alpine

# 设置工作目录
WORKDIR /app

# 复制 requirements.txt
COPY requirements.txt .

# 安装运行时系统依赖 + 构建依赖，pip install 后清理构建工具
# curl: 用于健康检查
# .build-deps: 虚拟包组，安装后即删除，不残留 gcc/musl-dev 等编译工具
RUN apk add --no-cache curl \
    && apk add --no-cache --virtual .build-deps gcc musl-dev libffi-dev openssl-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# 创建必要的目录结构
RUN mkdir -p /app/data

# 复制后端代码
COPY VERSION .
COPY main.py .
COPY tg_imagebed/ ./tg_imagebed/

# 从前端构建阶段复制构建产物
COPY --from=frontend-builder /frontend/.output/public /app/frontend/.output/public

# 暴露端口
EXPOSE 18793

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 CMD curl --noproxy localhost -f http://localhost:18793/api/health || exit 1

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 创建非 root 用户并切换
RUN adduser -D -s /bin/sh appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "main.py"]
