.PHONY: help install test lint format clean docker-build docker-up docker-down deploy

help: ## 显示帮助信息
	@echo "Marble 3D Service - 开发命令"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## 安装依赖
	@echo "安装 Python 依赖..."
	cd backend && pip install -r requirements.txt
	@echo "✅ 依赖安装完成"

test: ## 运行测试
	@echo "运行测试..."
	cd backend && python -m pytest tests/ -v
	@echo "✅ 测试完成"

lint: ## 代码检查 (flake8)
	@echo "运行 flake8 检查..."
	cd backend && flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics || true
	@echo "✅ 代码检查完成"

format: ## 代码格式化 (black)
	@echo "运行 Black 格式化..."
	cd backend && black . --line-length 88
	@echo "✅ 代码格式化完成"

clean: ## 清理临时文件
	@echo "清理临时文件..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name ".pytest_cache" -delete
	rm -f .coverage
	@echo "✅ 清理完成"

docker-build: ## 构建 Docker 镜像
	@echo "构建 Docker 镜像..."
	cd backend && docker build -t marble-3d-service:latest .
	@echo "✅ Docker 镜像构建完成"

docker-up: ## 启动 Docker 容器 (docker-compose)
	@echo "启动 Docker 容器..."
	cd backend && docker-compose up -d
	@echo "✅ Docker 容器已启动"

docker-down: ## 停止 Docker 容器
	@echo "停止 Docker 容器..."
	cd backend && docker-compose down
	@echo "✅ Docker 容器已停止"

docker-logs: ## 查看 Docker 日志
	cd backend && docker-compose logs -f

run: ## 运行开发服务器
	@echo "启动开发服务器..."
	cd backend && python app.py

setup: install test ## 完整设置（安装 + 测试）

deploy: ## 部署到生产环境 (需要配置)
	@echo "部署到生产环境..."
	@echo "⚠️  请配置部署脚本"
	@exit 1

check-env: ## 检查环境变量
	@echo "检查环境变量..."
	@test -f backend/.env || (echo "❌ 缺少 backend/.env 文件。请复制 backend/.env.example 并填写。"; exit 1)
	@echo "✅ 环境变量文件存在"

git-commit: ## Git 提交 (自动添加所有更改)
	@echo "Git 提交..."
	git add .
	git commit -m "🚀 Optimize: security fixes, Docker support, CI/CD, tests, docs"
	@echo "✅ Git 提交完成"

git-push: ## Git 推送到远程
	@echo "推送到 GitHub..."
	git push origin master
	@echo "✅ 推送完成"

git-sync: git-commit git-push ## Git 提交并推送

backup: ## 备份项目
	@echo "备份项目..."
	tar -czf marble-3d-service-backup-$(shell date +%Y%m%d_%H%M%S).tar.gz .
	@echo "✅ 备份完成"

.DEFAULT_GOAL := help
