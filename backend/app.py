# -*- coding: utf-8 -*-
"""
Marble 3D 世界生成服务 - 后端 API
"""

import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
from dotenv import load_dotenv

# 加载环境变量（从 .env 文件）— 必须在 routes.world 导入前执行
load_dotenv()

from extensions import limiter  # noqa: E402
from routes.world import world_bp  # noqa: E402

# 前端目录：统一指向项目根目录下的 frontend/，不再维护 backend/static 副本
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend')
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
GENERATED_3D_DIR = os.path.join(os.path.dirname(__file__), 'generated_3d_views')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
Path(GENERATED_3D_DIR).mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
CORS(app)
limiter.init_app(app)

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'dev-secret-key-change-in-production'
)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 注册蓝图
app.register_blueprint(world_bp, url_prefix='/api')


# 提供上传文件的访问
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(os.path.abspath(UPLOAD_DIR), filename)


# 提供 Stable Zero123 生成文件的访问
@app.route('/generated_3d_views/<path:filename>')
def serve_generated_3d(filename):
    return send_from_directory(os.path.abspath(GENERATED_3D_DIR), filename)


# 根路由
@app.route('/')
def index():
    return send_from_directory(FRONTEND_DIR, 'index.html')


# 静态文件
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# 健康检查
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'timestamp': datetime.now().isoformat()})


# API 文档 (Swagger UI)
@app.route('/api/docs')
def api_docs():
    """提供 Swagger UI 界面"""
    swagger_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Marble 3D Service API - Swagger UI</title>
        <link rel="stylesheet" type="text/css"
              href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
        <style>
            html, body { margin: 0; padding: 0; height: 100%; }
            #swagger-ui { max-width: 1460px; margin: 0 auto; }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {
                const ui = SwaggerUIBundle({
                    url: "/api/openapi.yaml",
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIStandalonePreset
                    ],
                });
                window.ui = ui;
            };
        </script>
    </body>
    </html>
    """
    return render_template_string(swagger_html)


# OpenAPI 规范文件
@app.route('/api/openapi.yaml')
def openapi_spec():
    """返回 OpenAPI 规范文件"""
    spec_path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'openapi.yaml')
    with open(spec_path, 'r', encoding='utf-8') as f:
        return f.read(), 200, {'Content-Type': 'text/yaml; charset=utf-8'}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
