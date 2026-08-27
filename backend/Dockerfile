FROM python:3.11-slim

# 构建上下文为项目根目录（含 backend/ frontend/ docs/）

WORKDIR /app

# 安装系统依赖（包括 Pillow 所需的图像处理库）
RUN apt-get update && apt-get install -y \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（核心 + 可选开源模型依赖）
COPY backend/requirements.txt backend/requirements-open-source.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-open-source.txt || \
    echo "⚠️ 可选依赖（torch/diffusers）安装失败，Stable Zero123/文生图将不可用"

# 创建必要目录
RUN mkdir -p /app/backend/generated_3d_views /app/uploads

# 复制应用代码与前端文件
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY docs/ ./docs/

WORKDIR /app/backend

# 暴露端口
EXPOSE 5000

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend

# 健康检查（使用标准库 urllib，不依赖 requests）
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# 启动命令（--timeout 600s 容纳 Stable Zero123 长时间生成）
CMD ["gunicorn", "-w", "4", "--timeout", "600", "-b", "0.0.0.0:5000", \
     "--access-logfile", "-", "--error-logfile", "-", "app:app"]
