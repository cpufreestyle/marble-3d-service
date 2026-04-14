# -*- coding: utf-8 -*-
"""
Marble 3D 世界生成服务 - 后端 API
"""

import os
os.environ.setdefault('WORLD_LABS_API_KEY', 'sMkQvlYoTzs8YS4jJDicJD20OZDWJlKe')

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import uuid
from datetime import datetime
from pathlib import Path

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'static')
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

from routes.world import world_bp

app = Flask(__name__)
CORS(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 注册蓝图
app.register_blueprint(world_bp, url_prefix='/api')

# 提供上传文件的访问
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(os.path.abspath(UPLOAD_DIR), filename)

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
