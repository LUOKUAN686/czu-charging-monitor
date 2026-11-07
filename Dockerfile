# 使用轻量级官方 Python 镜像，极小体积、极速冷启动
FROM python:3.12-slim

# 禁用 Python 缓存写入与缓冲，确保日志实时直出
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# 复制依赖配置并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制生产运行主文件
COPY app_cloud_run.py .

# 暴露 Cloud Run 标准端口
EXPOSE 8080

# 启动命令
CMD ["python", "app_cloud_run.py"]
