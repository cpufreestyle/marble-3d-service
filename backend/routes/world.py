# -*- coding: utf-8 -*-
"""
World Labs API 路由
"""

from flask import Blueprint, request, jsonify
import os
import requests

world_bp = Blueprint('world', __name__)

# World Labs API 配置
API_KEY = 'sMkQvlYoTzs8YS4jJDicJD20OZDWJlKe'
API_URL = 'https://api.worldlabs.ai/marble/v1'

@world_bp.route('/create', methods=['POST'])
def create_world():
    """创建 3D 世界"""
    try:
        prompt = ''
        if request.json:
            prompt = request.json.get('prompt', '')
        
        if not prompt:
            return jsonify({'success': False, 'error': '请输入提示词'}), 400
        
        headers = {
            'WLT-Api-Key': API_KEY,
            'Content-Type': 'application/json'
        }
        
        payload = {
            "display_name": prompt[:50] or "My World",
            "world_prompt": {
                "type": "text",
                "text_prompt": prompt
            }
        }
        
        response = requests.post(
            f'{API_URL}/worlds:generate',
            headers=headers,
            json=payload,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            result = response.json()
            return jsonify({
                'success': True,
                'task_id': result.get('operation_id'),
                'status': 'processing'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'API 错误: {response.status_code}',
                'details': response.text[:1000]
            }), response.status_code
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@world_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        headers = {'WLT-Api-Key': API_KEY}
        
        response = requests.get(
            f'{API_URL}/operations/{task_id}',
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            done = result.get('done', False)
            
            if done:
                world_data = result.get('response', {})
                assets = world_data.get('assets', {})
                splats = assets.get('splats', {}).get('spz_urls', {})
                mesh = assets.get('mesh', {})
                imagery = assets.get('imagery', {})
                
                thumb = assets.get('thumbnail_url', '')
                pano = imagery.get('pano_url', '')
                
                return jsonify({
                    'success': True,
                    'status': 'completed',
                    'result': {
                        'world_id': world_data.get('id', ''),
                        'world_url': world_data.get('world_marble_url', ''),
                        'preview_url': thumb or pano,
                        'pano_url': pano,
                        'thumbnail_url': thumb,
                        'caption': assets.get('caption', ''),
                        'spz_100k': splats.get('100k', ''),
                        'spz_500k': splats.get('500k', ''),
                        'spz_full': splats.get('full_res', ''),
                        'mesh_url': mesh.get('collider_mesh_url', ''),
                    }
                })
            else:
                return jsonify({
                    'success': True,
                    'status': 'processing',
                    'progress': '生成中...'
                })
        else:
            return jsonify({
                'success': False,
                'error': f'获取状态失败: {response.status_code}'
            }), response.status_code
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
