# -*- coding: utf-8 -*-
"""
World Labs API 路由 - 支持提示词优化 + 图片上传
优化版本：修复安全漏洞、语法错误，添加日志和错误处理
"""

from flask import Blueprint, request, jsonify, send_from_directory
import os
from dotenv import load_dotenv
import requests
import uuid
import base64
from pathlib import Path
from datetime import datetime
import logging

# 加载环境变量
load_dotenv()

world_bp = Blueprint('world', __name__)

# World Labs API 配置
API_KEY = os.environ.get('WORLD_LABS_API_KEY')
if not API_KEY:
    raise ValueError("❌ 缺少 WORLD_LABS_API_KEY 环境变量。请在 .env 文件中设置。")

API_URL = 'https://api.worldlabs.ai/marble/v1'

# 本地 LLM 配置
LM_STUDIO_URL = os.environ.get('LM_STUDIO_URL', 'http://localhost:1234/v1')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)


def check_local_llm():
    """检测可用的本地 LLM"""
    # 检查 LM Studio
    try:
        r = requests.get(f'{LM_STUDIO_URL}/models', timeout=2)
        if r.status_code == 200:
            logging.info(f"检测到 LM Studio: {LM_STUDIO_URL}")
            return 'lmstudio', LM_STUDIO_URL
    except Exception as e:
        logging.debug(f"LM Studio 检测失败: {e}")

    # 检查 Ollama
    try:
        r = requests.get(f'{OLLAMA_URL}/api/tags', timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data.get('models'):
                logging.info(f"检测到 Ollama: {OLLAMA_URL}")
                return 'ollama', OLLAMA_URL
    except Exception as e:
        logging.debug(f"Ollama 检测失败: {e}")

    return None, None


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
                enhanced = response.json()['choices'][0]['message']['content']
                logging.info(f"LM Studio 提示词优化成功: {prompt[:50]}...")
                return enhanced

        elif llm_type == 'ollama':
            response = requests.post(
                f'{llm_url}/api/generate',
                json={
                    'model': 'qwen2.5:7b',
                    'prompt': f"{system_prompt}\n\n输入: {prompt}\n输出:",
                    'stream': False
                },
                timeout=30
            )
            if response.status_code == 200:
                enhanced = response.json().get('response', prompt)
                logging.info(f"Ollama 提示词优化成功: {prompt[:50]}...")
                return enhanced

    except Exception as e:
        logging.warning(f"本地 LLM 调用失败: {e}")

    return None


@world_bp.route('/llm-status', methods=['GET'])
def get_llm_status():
    """获取本地 LLM 状态"""
    try:
        llm_type, llm_url = check_local_llm()
        if llm_type:
            return jsonify({
                'success': True,
                'available': True,
                'type': llm_type,
                'url': llm_url
            })
        return jsonify({
            'success': True,
            'available': False,
            'message': '未检测到本地 LLM。请在 LM Studio 启动 Local Server (端口 1234) 或运行 Ollama。'
        })
    except Exception as e:
        logging.error(f"检查 LLM 状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


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
            logging.info(f"图片上传成功: {filename}")
            return jsonify({
                'success': True,
                'url': image_url,
                'filename': filename
            })

    except Exception as e:
        logging.error(f"图片上传失败: {e}")
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

        # 支持 multipart/form-data 或 application/json
        if request.content_type and 'multipart/form-data' in request.content_type:
            prompt = request.form.get('prompt', '')
            user_api_key = request.form.get('api_key', '')
            use_local_llm = request.form.get('use_local_llm', 'true').lower() == 'true'
            image_file = request.files.get('image')

            if image_file and image_file.filename:
                ext = os.path.splitext(image_file.filename)[1].lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                    return jsonify({'success': False, 'error': '只支持 JPG/PNG/WEBP 格式'}), 400

                filename = f"{uuid.uuid4().hex}{ext}"
                filepath = os.path.join(UPLOAD_DIR, filename)
                image_file.save(filepath)
                image_url = f"{request.host_url}uploads/{filename}".replace('http://', 'https://')

        elif request.is_json:
            data = request.get_json()
            prompt = data.get('prompt', '')
            user_api_key = data.get('api_key', '')
            use_local_llm = data.get('use_local_llm', True)
            image_url = data.get('image_url')

        if not prompt and not image_url:
            return jsonify({'success': False, 'error': '请输入提示词或上传图片'}), 400

        # 使用用户提供的 Key 或默认 Key
        api_key = user_api_key if user_api_key else API_KEY

        # 检查并使用本地 LLM 优化提示词
        final_prompt = prompt
        llm_used = None

        if use_local_llm and prompt:
            llm_type, llm_url = check_local_llm()
            if llm_type:
                enhanced = enhance_prompt_with_local_llm(prompt, llm_type, llm_url)
                if enhanced:
                    final_prompt = enhanced
                    llm_used = llm_type
                    logging.info(f"使用 {llm_type} 优化提示词: {prompt} -> {final_prompt}")

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

        logging.info(f"创建 3D 世界: prompt={final_prompt[:100]}...")
        response = requests.post(
            f'{API_URL}/worlds:generate',
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code in [200, 201]:
            result = response.json()
            logging.info(f"任务创建成功: task_id={result.get('operation_id')}")
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
            logging.error(f"API 错误: {response.status_code} - {response.text[:200]}")
            return jsonify({
                'success': False,
                'error': f'API 错误: {response.status_code}',
                'details': response.text[:1000]
            }), response.status_code

    except Exception as e:
        logging.error(f"创建世界失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        user_api_key = request.args.get('api_key', '')
        api_key = user_api_key if user_api_key else API_KEY

        headers = {'WLT-Api-Key': api_key}

        logging.info(f"查询任务状态: task_id={task_id}")
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

                logging.info(f"任务完成: task_id={task_id}")
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
            logging.error(f"获取状态失败: {response.status_code} - {response.text[:200]}")
            return jsonify({
                'success': False,
                'error': f'获取状态失败: {response.status_code}'
            }), response.status_code

    except Exception as e:
        logging.error(f"查询任务状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
