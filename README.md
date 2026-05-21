# Marble 3D 世界生成服务

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.3+-lightgrey.svg)](https://flask.palletsprojects.com/)

🎲 用中文提示词生成 3D 世界

---

## 功能特点

- 📝 **中文输入** - 直接用中文描述你的想象
- 🖼️ **图片转 3D** - 支持上传图片生成 
- 🎮 **交互式预览** - 生成后可交互查看 3D 世界
- 💡 **示例画廊** - 快速参考示例
- 🤖 **本地 LLM 支持** - 可选使用 LM Studio 或 Ollama 优化提示词

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

### 1. 克隆项目

```bash
git clone https://github.com/yourusername/marble-3d-service.git
cd marble-3d-service
```

### 2. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 创建 .env 文件
cp .env.example .env
```

编辑 `.env` 文件，设置 World Labs API Key：

```env
WORLD_LABS_API_KEY=your_api_key_here
SECRET_KEY=your_secret_key
```

> ⚠️ **重要**: 请前往 [World Labs AI](https://worldlabs.ai) 获取 API Key

### 4. 启动后端

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

**参数：**
- `api_key` (query, optional): 自定义 API Key

**响应：**
```json
{
  "success": true,
  "status": "completed",
  "result": {
    "world_id": "xxx",
    "world_url": "https://marble.worldlabs.ai/world/xxx",
    "preview_url": "https://xxx.jpg",
    "pano_url": "https://xxx.jpg",
    "thumbnail_url": "https://xxx.jpg",
    "caption": "世界描述",
    "spz_100k": "https://...",
    "spz_500k": "https://...",
    "spz_full": "https://...",
    "mesh_url": "https://..."
  }
}
```

### 检查本地 LLM 状态

```
GET /api/llm-status
```

**响应：**
```json
{
  "success": true,
  "available": true,
  "type": "lmstudio",
  "url": "http://localhost:1234"
}
```

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

## 环境变量说明

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `WORLD_LABS_API_KEY` | ✅ | World Labs API 密钥 |
| `SECRET_KEY` | ❌ | Flask 密钥（生产环境必填） |
| `PORT` | ❌ | 服务器端口（默认 5000） |

## 本地 LLM 支持（可选）

服务支持使用本地 LLM（LM Studio 或 Ollama）优化中文提示词：

1. **LM Studio**: 启动 Local Server（默认端口 1234）
2. **Ollama**: 运行 `ollama serve`（默认端口 11434）

服务会自动检测并使用的本地 LLM，将中文提示词优化为更详细的英文描述。

## 许可证

MIT License

---

## 鸣谢

- [World Labs AI](https://worldlabs.ai) - 3D 世界生成 API
- [Flask](https://flask.palletsprojects.com/) - Web 框架
- [LM Studio](https://lmstudio.ai/) - 本地 LLM 运行环境
- [Ollama](https://ollama.com/) - 本地 LLM 运行环境
