# -*- coding: utf-8 -*-
"""
Marble 3D 世界生成服务 - 后端 API
"""

import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# 注册蓝图
app.register_blueprint(world_bp, url_prefix='/api')

# 初始化 WebSocket 推送
from routes.world import init_socketio_emit
init_socketio_emit(socketio)

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


# ==================== WebSocket 事件 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    from flask import session
    client_id = request.sid
    print(f'[WS] Client connected: {client_id}')
    emit('connected', {'client_id': client_id, 'message': 'Marble 3D 服务已连接'})


@socketio.on('disconnect')
def handle_disconnect():
    print(f'[WS] Client disconnected: {request.sid}')


@socketio.on('subscribe_task')
def handle_subscribe_task(data):
    """订阅任务进度更新"""
    task_id = data.get('task_id')
    if task_id:
        join_room(task_id)
        emit('subscribed', {'task_id': task_id, 'message': f'已订阅任务 {task_id} 的进度更新'})


@socketio.on('unsubscribe_task')
def handle_unsubscribe_task(data):
    """取消订阅任务"""
    task_id = data.get('task_id')
    if task_id:
        leave_room(task_id)
        emit('unsubscribed', {'task_id': task_id})


@socketio.on('ping')
def handle_ping():
    """心跳检测"""
    emit('pong', {'timestamp': datetime.now().isoformat()})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'[INFO] Marble 3D 服务启动，端口 {port}')
    print(f'[INFO] WebSocket 已启用')
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
