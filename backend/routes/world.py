# -*- coding: utf-8 -*-
"""
World Labs API 路由 - 支持提示词优化 + 图片上传
"""

from flask import Blueprint, request, jsonify, send_from_directory
import os
import requests
import uuid
import base64
from pathlib import Path

world_bp = Blueprint('world', __name__)

# World Labs API 配置
API_KEY = 'sMkQvlYoTzs8YS4jJDicJD20OZDWJlKe'
API_URL = 'https://api.worldlabs.ai/marble/v1'

# 本地 LLM 配置（手动选择）
LM_STUDIO_URL = 'http://localhost:1234/v1'
OLLAMA_URL = 'http://localhost:11434'

# 默认 LLM 类型: 'lmstudio' | 'ollama' | 'auto'（自动检测）
DEFAULT_LLM = os.environ.get('DEFAULT_LLM', 'auto')

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


def get_local_llm(preferred=None):
    """获取用户选择的本地 LLM"""
    if preferred and preferred != 'auto':
        # 手动选择
        if preferred == 'lmstudio':
            try:
                r = requests.get(f'{LM_STUDIO_URL}/models', timeout=2)
                if r.status_code == 200:
                    return 'lmstudio', LM_STUDIO_URL
            except:
                return None, None
        elif preferred == 'ollama':
            try:
                r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=2)
                if r.status_code == 200 and r.json().get('models'):
                    return 'ollama', OLLAMA_URL
            except:
                return None, None
        return None, None
    
    # auto 模式：按优先级检测
    # 检查 LM Studio
    try:
        r = requests.get(f'{LM_STUDIO_URL}/models', timeout=2)
        if r.status_code == 200:
            return 'lmstudio', LM_STUDIO_URL
    except:
        pass

    # 检查 Ollama
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data.get('models'):
                return 'ollama', OLLAMA_URL
    except:
        pass

    return None, None


def check_local_llm():
    """检测可用的本地 LLM（兼容旧接口）"""
    return get_local_llm()


@world_bp.route('/llm-status', methods=['GET'])
def get_llm_status():
    """获取本地 LLM 状态"""
    status = {'lmstudio': False, 'ollama': False}
    
    # 检查 LM Studio
    try:
        r = requests.get(f'{LM_STUDIO_URL}/models', timeout=2)
        if r.status_code == 200:
            models = r.json().get('data', [])
            status['lmstudio'] = {'available': True, 'models': [m.get('id') for m in models]}
    except:
        pass

    # 检查 Ollama
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=2)
        if r.status_code == 200:
            data = r.json()
            status['ollama'] = {'available': True, 'models': [m.get('name') for m in data.get('models', [])]}
    except:
        pass

    return jsonify({
        'success': True,
        'default': DEFAULT_LLM,
        'status': status
    })


def enhance_prompt_with_local_llm(prompt, llm_type, llm_url):
    """使用本地 LLM 优化提示词"""
    system_prompt = """你是一个 3D 世界生成专家。用户的中文描述会被翻译成英文，并添加细节让 3D 场景更生动。

规则：
1. 翻译成英文
2. 添加环境细节（光照、氛围、材质）
3. 保持简洁，不超过 100 个单词
4. 直接输出优化后的英文提示词，不要解释

示例：
输入: 一只可爱的橘猫坐在阳光明媚的窗台上
输出: A cute orange tabby cat sitting on a sunlit windowsill, soft morning light streaming through lace curtains, warm cozy atmosphere, wooden window frame, indoor plants nearby, photorealistic, soft shadows, golden hour lighting"""

    try:
        if llm_type == 'lmstudio':
            response = requests.post(
                f'{llm_url}/chat/completions',
                json={
                    'model': 'local-model',
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': prompt}
                    ],
                    'temperature': 0.7,
                    'max_tokens': 200
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json()['choices'][0]['message']['content']

        elif llm_type == 'ollama':
            response = requests.post(
                f'{llm_url}/api/generate',
                json={
                    'model': 'mistral:7b',  # 使用已安装的模型
                    'prompt': f"{system_prompt}\n\n输入: {prompt}\n输出:",
                    'stream': False
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json().get('response', prompt)

    except Exception as e:
        print(f"[WARN] 本地 LLM 调用失败: {e}")

    return None


@world_bp.route('/upload-image', methods=['POST'])
def upload_image():
    """上传图片，返回 URL"""
    try:
        if 'image' not in request.files and 'image' not in request.form:
            return jsonify({'success': False, 'error': '没有上传图片'}), 400

        image_file = request.files.get('image')
        if image_file and image_file.filename:
            ext = os.path.splitext(image_file.filename)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                return jsonify({'success': False, 'error': '只支持 JPG/PNG/WEBP 格式'}), 400

            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(UPLOAD_DIR, filename)
            image_file.save(filepath)

            # 返回可访问的 URL
            image_url = f"/uploads/{filename}"
            return jsonify({
                'success': True,
                'url': image_url,
                'filename': filename
            })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供上传文件的访问"""
    return send_from_directory(UPLOAD_DIR, filename)


@world_bp.route('/create', methods=['POST'])
def create_world():
    """创建 3D 世界（支持图片上传）"""
    try:
        prompt = ''
        user_api_key = ''
        use_local_llm = True
        image_url = None
        llm_type = DEFAULT_LLM  # 默认 LLM 选择

        # 支持 multipart/form-data 或 application/json
        if request.content_type and 'multipart/form-data' in request.content_type:
            prompt = request.form.get('prompt', '')
            user_api_key = request.form.get('api_key', '')
            use_local_llm = request.form.get('use_local_llm', 'true').lower() == 'true'
            llm_type = request.form.get('llm_type', DEFAULT_LLM)  # 新增：手动选择 LLM
            image_file = request.files.get('image')

            if image_file and image_file.filename:
                ext = os.path.splitext(image_file.filename)[1].lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                    return jsonify({'success': False, 'error': '只支持 JPG/PNG/WEBP 格式'}), 400

                filename = f"{uuid.uuid4().hex}{ext}"
                filepath = os.path.join(UPLOAD_DIR, filename)
                image_file.save(filepath)
                image_url = f"{request.host_url}uploads/{filename}".replace('http://', 'https://')

        elif request.json:
            prompt = request.json.get('prompt', '')
            user_api_key = request.json.get('api_key', '')
            use_local_llm = request.json.get('use_local_llm', True)
            llm_type = request.json.get('llm_type', DEFAULT_LLM)  # 新增：手动选择 LLM
            image_url = request.json.get('image_url')

        if not prompt and not image_url:
            return jsonify({'success': False, 'error': '请输入提示词或上传图片'}), 400

        # 使用用户提供的 Key 或默认 Key
        api_key = user_api_key if user_api_key else API_KEY

        # 检查并使用本地 LLM 优化提示词
        final_prompt = prompt
        llm_used = None

        if use_local_llm and prompt:
            # 使用手动选择的 LLM 或自动检测
            llm_type, llm_url = get_local_llm(llm_type)
            if llm_type:
                enhanced = enhance_prompt_with_local_llm(prompt, llm_type, llm_url)
                if enhanced:
                    final_prompt = enhanced
                    llm_used = llm_type
                    print(f"[INFO] 使用 {llm_type} 优化提示词: {prompt} -> {final_prompt}")

        headers = {
            'WLT-Api-Key': api_key,
            'Content-Type': 'application/json'
        }

        # 构建 world_prompt：优先图片，否则文本
        if image_url:
            world_prompt = {
                "type": "image_url",
                "image_url": {
                    "url": image_url
                }
            }
        else:
            world_prompt = {
                "type": "text",
                "text_prompt": final_prompt
            }

        payload = {
            "display_name": (final_prompt or "Image World")[:50] or "My World",
            "world_prompt": world_prompt
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
                'status': 'processing',
                'original_prompt': prompt,
                'enhanced_prompt': final_prompt if final_prompt != prompt else None,
                'llm_used': llm_used,
                'image_url': image_url
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
        user_api_key = request.args.get('api_key', '')
        api_key = user_api_key if user_api_key else API_KEY

        headers = {'WLT-Api-Key': api_key}

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
