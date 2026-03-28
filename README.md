# Marble 3D 世界生成服务

🎲 用中文提示词生成 3D 世界

## 功能特点

- 📝 **中文输入** - 直接用中文描述你的想象
- 🖼️ **图片转 3D** - 也支持上传图片生成
- 🎮 **交互式预览** - 生成后可交互查看 3D 世界
- 💡 **示例画廊** - 快速参考示例

## 系统架构

```
用户(中文) 
    ↓
后端 Flask API
    ↓
[可选] 翻译 → World Labs API
    ↓
返回 3D 世界 URL
```

## 快速开始

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 创建 .env 文件
cp .env.example .env
```

编辑 `.env` 文件，设置 World Labs API Key：

```
WORLD_LABS_API_KEY=your_api_key_here
SECRET_KEY=your_secret_key
```

### 3. 启动后端

```bash
python app.py
```

后端将在 http://localhost:5000 运行

### 4. 部署前端

#### 方式 A：独立服务器

将 `frontend/index.html` 部署到任何静态托管服务（Vercel、Netlify、Nginx 等）

#### 方式 B：与 Flask 后端一起

将前端文件复制到 Flask 的 static 目录：

```bash
mkdir -p backend/static
cp frontend/index.html backend/static/
```

然后访问 http://localhost:5000

## API 文档

### 创建 3D 世界

```
POST /api/create
```

**参数：**
- `prompt` (string): 提示词
- `image` (file, optional): 图片文件

**响应：**
```json
{
  "success": true,
  "task_id": "xxx",
  "status": "completed",
  "result": {
    "world_url": "https://marble.worldlabs.ai/world/xxx",
    "preview_url": "https://xxx.jpg"
  }
}
```

### 获取任务状态

```
GET /api/task/<task_id>
```

## 支付集成（预留）

如需集成支付宝/微信支付，可以：

1. 在 `create_world` 接口中添加用户认证
2. 集成支付 SDK
3. 记录用户余额和消费

## 部署到生产环境

### 使用 Gunicorn

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### 使用 Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

## 环境要求

- Python 3.8+
- Flask 2.3+
- requests

## 许可证

MIT License
