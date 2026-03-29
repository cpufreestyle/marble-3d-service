# -*- coding: utf-8 -*-
"""
Marble 3D 世界生成服务 - 后端 API
"""

import os
# 设置 API Key（必须在导入其他模块之前）
os.environ.setdefault('WORLD_LABS_API_KEY', 'sMkQvlYoTzs8YS4jJDicJD20OZDWJlKe')

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import uuid
from datetime import datetime
from pathlib import Path

# 获取前端文件路径
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), 'static')

# 导入路由
from routes.world import world_bp

app = Flask(__name__)
CORS(app)

# 配置
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# 确保上传目录存在
Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

# 注册蓝图
app.register_blueprint(world_bp, url_prefix='/api')

# 根路由 - 返回前端页面
@app.route('/')
def index():
    return send_from_directory(FRONTEND_DIR, 'index.html')

# 静态文件服务
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
