# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### 🔒 Security
- 移除硬编码的 API Key（app.py, world.py）
- 添加 `.env.example` 和环境变量支持
- 创建 `.gitignore` 防止敏感文件提交

### 🐛 Bug Fixes
- 修复 `world.py` 中的语法错误（字典缺少逗号）
- 修复 `request.json` 判断逻辑（使用 `request.is_json`）
- 修复日志记录格式

### ✨ Added
- 添加 Docker 支持（Dockerfile, docker-compose.yml）
- 添加日志配置和错误处理
- 添加 API 文档（README.md）
- 添加测试用例（tests/test_api.py）
- 添加 GitHub Actions CI/CD（.github/workflows/ci.yml）
- 添加 CHANGELOG.md

### 🔧 Changed
- 更新 `requirements.txt`（添加 python-dotenv）
- 优化 `README.md`（完整文档、架构图、API 文档）
- 重构 `world.py`（添加日志、错误处理、环境变量支持）

### 🗑️ Removed
- 移除硬编码的 API Key

---

## [1.0.0] - 2026-04-14

### ✨ Added
- 初始版本发布
- 支持中文提示词生成 3D 世界
- 支持图片上传生成 3D 世界
- 支持本地 LLM（LM Studio / Ollama）优化提示词
- 提供交互式 3D 世界预览
- 提供示例画廊

---

## [0.1.0] - 2026-03-28

### ✨ Added
- 项目初始化
- Flask 后端框架搭建
- World Labs API 集成

---

## 版本号说明

本项目遵循 [语义化版本 2.0.0](https://semver.org/lang/zh-CN/)：

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

---

## 如何更新 CHANGELOG

1. 在 `[Unreleased]` 部分添加你的更改
2. 按照以下分类组织：
   - `### 🔒 Security` - 安全相关
   - `### 🐛 Bug Fixes` - Bug 修复
   - `### ✨ Added` - 新功能
   - `### 🔧 Changed` - 功能变更
   - `### ⚡ Performance` - 性能优化
   - `### 🗑️ Removed` - 移除的功能
   - `### 📝 Documentation` - 文档更新
3. 提交前移动到对应的版本号下

---

**完整历史**：请查看 [GitHub Releases](https://github.com/cpufreestyle/marble-3d-service/releases)
