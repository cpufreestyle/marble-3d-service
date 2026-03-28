# -*- coding: utf-8 -*-
"""
World Labs API 路由
"""

from flask import Blueprint, request, jsonify
import os
import json
import uuid
import requests
from datetime import datetime
from werkzeug.utils import secure_filename

world_bp = Blueprint('world', __name__)

# World Labs API 配置
WORLD_LABS_API_KEY = os.environ.get('WORLD_LABS_API_KEY', '')
WORLD_LABS_API_URL = 'https://api.worldlabs.ai/v1'

# 允许的文件扩展名
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def translate_to_english(text):
    """
    翻译中文提示词到英文（可选功能）
    这里使用简单的规则，也可以接入翻译API
    """
    # 简单场景：直接返回（假设用户可能直接用英文）
    # 实际生产中可以使用 Google Translate API 或其他翻译服务
    return text

@world_bp.route('/create', methods=['POST'])
def create_world():
    """
    创建 3D 世界
    支持参数:
    - prompt: 文本提示词
    - image: 图片文件（可选）
    - mode: generation mode
    """
    try:
        # 获取请求数据
        data = request.form or request.json or {}
        prompt = data.get('prompt', '')
        mode = data.get('mode', 'text-to-world')
        
        # 处理图片上传
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
                filepath = os.path.join(
                    request.app.config['UPLOAD_FOLDER'] if hasattr(request, 'app') else 'uploads',
                    filename
                )
                file.save(filepath)
                image_url = f"/uploads/{filename}"
        
        # 如果没有提供 prompt 或 image，返回错误
        if not prompt and not image_url:
            return jsonify({
                'success': False,
                'error': '请提供提示词或上传图片'
            }), 400
        
        # 翻译提示词（可选）
        prompt_en = translate_to_english(prompt)
        
        # 调用 World Labs API
        if not WORLD_LABS_API_KEY:
            # 模拟API调用（开发测试用）
            return jsonify({
                'success': True,
                'task_id': str(uuid.uuid4()),
                'status': 'processing',
                'message': 'World Labs API Key 未配置，请先设置环境变量 WORLD_LABS_API_KEY',
                # 模拟返回
                'result': {
                    'world_url': 'https://marble.worldlabs.ai/world/demo-123',
                    'preview_url': 'https://example.com/preview.jpg'
                }
            })
        
        # 实际 API 调用
        headers = {
            'Authorization': f'Bearer {WORLD_LABS_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        payload = {
            'prompt': prompt_en or prompt,
            'mode': mode
        }
        
        if image_url:
            payload['image_url'] = image_url
        
        # 发送请求
        response = requests.post(
            f'{WORLD_LABS_API_URL}/generate',
            headers=headers,
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return jsonify({
                'success': True,
                'task_id': result.get('task_id', str(uuid.uuid4())),
                'status': 'completed',
                'result': result
            })
        else:
            return jsonify({
                'success': False,
                'error': f'API 调用失败: {response.status_code}',
                'details': response.text
            }), response.status_code
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@world_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        if not WORLD_LABS_API_KEY:
            return jsonify({
                'success': True,
                'task_id': task_id,
                'status': 'completed',
                'result': {
                    'world_url': f'https://marble.worldlabs.ai/world/{task_id}',
                    'preview_url': 'https://example.com/preview.jpg'
                }
            })
        
        headers = {
            'Authorization': f'Bearer {WORLD_LABS_API_KEY}',
        }
        
        response = requests.get(
            f'{WORLD_LABS_API_URL}/tasks/{task_id}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'task_id': task_id,
                'status': response.json().get('status', 'completed'),
                'result': response.json()
            })
        else:
            return jsonify({
                'success': False,
                'error': f'获取任务状态失败: {response.status_code}'
            }), response.status_code
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@world_bp.route('/gallery', methods=['GET'])
def get_gallery():
    """获取示例/ gallery"""
    # 这里可以从数据库或文件读取历史记录
    return jsonify({
        'success': True,
        'examples': [
            {
                'id': '1',
                'prompt': 'A cozy coffee shop with warm lighting',
                'preview_url': 'https://example.com/1.jpg',
                'world_url': 'https://marble.worldlabs.ai/world/1'
            },
            {
                'id': '2', 
                'prompt': 'Futuristic city street at night',
                'preview_url': 'https://example.com/2.jpg',
                'world_url': 'https://marble.worldlabs.ai/world/2'
            }
        ]
    })

# 路由：上传图片
@world_bp.route('/upload', methods=['POST'])
def upload_image():
    """处理图片上传"""
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False,
                'error': '没有上传文件'
            }), 400
        
        file = request.files['image']
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': '未选择文件'
            }), 400
        
        if file and allowed_file(file.filename):
            filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
            filepath = os.path.join('uploads', filename)
            file.save(filepath)
            
            return jsonify({
                'success': True,
                'url': f'/uploads/{filename}',
                'filename': filename
            })
        else:
            return jsonify({
                'success': False,
                'error': '不支持的文件类型'
            }), 400
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
