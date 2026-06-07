# 🎲 Marble 3D Service

**用中文提示词生成 3D 世界** - 基于 World Labs API 的智能 3D 场景生成服务

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-green.svg)]()
[![Flask](https://img.shields.io/badge/Flask-3.0-red.svg)]()

---

## ✨ 特性

- 📝 **中文输入** - 直接用中文描述你的想象
- 🖼️ **图片转 3D** - 支持上传图片生成 3D 世界
- 🎮 **交互式预览** - 生成后可交互查看 3D 世界
- 💡 **示例画廊** - 快速参考示例
- 🤖 **本地 LLM 支持** - 可选使用 LM Studio 或 Ollama 优化提示词
- 🐳 **Docker 支持** - 一键部署
- 🔒 **安全优化** - 环境变量管理 API Key，防止泄露

---

## 🏗️ 架构

```
用户(中文)
   ↓
后端 Flask API
   ↓
[可选] 本地 LLM 优化提示词 → World Labs API
   ↓
返回 3D 世界 URL
```

---

## 🚀 快速开始

### 1️⃣ 克隆仓库

```bash
git clone https://github.com/cpufreestyle/marble-3d-service.git
cd marble-3d-service
```

### 2️⃣ 获取 World Labs API Key

前往 [World Labs AI](https://worldlabs.ai) 注册并获取 API Key

### 3️⃣ 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env 文件，填入你的 API Key
```

`.env` 文件内容：

```bash
WORLD_LABS_API_KEY=your_api_key_here
SECRET_KEY=your_secret_key_change_in_production
PORT=5000
DEBUG=False
```

### 4️⃣ 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 5️⃣ 运行服务

```bash
python app.py
```

后端将在 [http://localhost:5000](http://localhost:5000) 运行

### 6️⃣ 访问前端

将 `frontend/index.html` 部署到任何静态托管服务（Vercel、Netlify、Nginx 等），或直接访问后端根路由。

---

## 🐳 Docker 部署

### 使用 Docker Compose（推荐）

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入 API Key

docker-compose up -d
```

服务将在 `http://localhost:5000` 运行

### 手动构建 Docker 镜像

```bash
cd backend
docker build -t marble-3d-service .
docker run -p 5000:5000 --env-file .env marble-3d-service
```

---

## 🤖 本地 LLM 支持（可选）

服务支持使用本地 LLM（LM Studio 或 Ollama）优化中文提示词：

### LM Studio

1. 下载并安装 [LM Studio](https://lmstudio.ai/)
2. 加载一个模型（推荐 Qwen2.5 7B 或类似模型）
3. 启动 Local Server（默认端口 `1234`）
4. 服务将自动检测并使用

### Ollama

1. 下载并安装 [Ollama](https://ollama.com/)
2. 运行 `ollama serve`（默认端口 `11434`）
3. 拉取模型：`ollama pull qwen2.5:7b`
4. 服务将自动检测并使用

---

## 📚 API 文档

### POST `/api/create`

创建 3D 世界

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `prompt` | string | 否* | 提示词（中文或英文） |
| `image` | file | 否* | 图片文件（JPG/PNG/WEBP） |
| `api_key` | string | 否 | 自定义 World Labs API Key |
| `use_local_llm` | boolean | 否 | 是否使用本地 LLM 优化提示词（默认 `true`） |

*注：`prompt` 和 `image` 至少提供一个

**响应：**

```json
{
  "success": true,
  "task_id": "xxx",
  "status": "processing",
  "original_prompt": "一只可爱的猫",
  "enhanced_prompt": "A cute cat...",
  "llm_used": "lmstudio",
  "image_url": null
}
```

---

### GET `/api/task/<task_id>`

获取任务状态

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `api_key` | query | 否 | 自定义 API Key |

**响应（处理中）：**

```json
{
  "success": true,
  "status": "processing",
  "progress": "生成中..."
}
```

**响应（完成）：**

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

---

### GET `/api/llm-status`

获取本地 LLM 状态

**响应：**

```json
{
  "success": true,
  "available": true,
  "type": "lmstudio",
  "url": "http://localhost:1234"
}
```

---

## 🛠️ 开发

### 项目结构

```
marble-3d-service/
├── backend/                # Flask 后端
│   ├── app.py            # 主应用
│   ├── routes/           # 路由
│   │   └── world.py     # World Labs API 路由
│   ├── utils/            # 工具函数
│   ├── models/           # 数据模型
│   ├── static/           # 静态文件（前端）
│   ├── uploads/          # 上传文件目录
│   ├── requirements.txt  # Python 依赖
│   ├── .env.example      # 环境变量示例
│   ├── Dockerfile        # Docker 配置
│   └── docker-compose.yml # Docker Compose 配置
├── frontend/             # 前端（可选）
│   └── index.html       # 前端页面
├── uploads/              # 上传文件（符号链接到 backend/uploads）
├── .gitignore           # Git 忽略文件
└── README.md            # 项目文档
```

### 运行测试

```bash
cd backend
pytest tests/
```

### 代码格式化

```bash
pip install black flake8
black backend/
flake8 backend/
```

---

## 🔒 安全注意事项

⚠️ **重要：**

1. **永远不要提交 `.env` 文件到 Git**
   - 已添加到 `.gitignore`
   - 使用 `.env.example` 作为模板

2. **生产环境必须修改 `SECRET_KEY`**
   - 不要使用默认的 `dev-secret-key`

3. **API Key 安全**
   - 默认从环境变量读取
   - 支持用户自定义 API Key（通过请求参数）

4. **文件上传限制**
   - 默认限制 16MB
   - 仅允许 JPG/PNG/WEBP 格式

---

## 📝 更新日志

查看 [CHANGELOG.md](CHANGELOG.md) 了解版本更新历史

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开一个 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

---

## 🙏 致谢

- [World Labs AI](https://worldlabs.ai) - 3D 世界生成 API
- [Flask](https://flask.palletsprojects.com/) - Web 框架
- [LM Studio](https://lmstudio.ai/) - 本地 LLM 运行环境
- [Ollama](https://ollama.com/) - 本地 LLM 运行环境

---

## 📧 联系

如有问题或建议，欢迎提交 Issue 或联系项目维护者。

**GitHub Issues**: [https://github.com/cpufreestyle/marble-3d-service/issues](https://github.com/cpufreestyle/marble-3d-service/issues)
