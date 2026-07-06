# -*- coding: utf-8 -*-
"""
World Labs API 路由 - 支持提示词优化 + 图片上传
优化版本：修复安全漏洞、语法错误，添加日志和错误处理
"""

import os
import time
import threading
import asyncio
import logging
import uuid
from pathlib import Path
from datetime import datetime, timedelta

import requests
from flask import Blueprint, request, jsonify, send_from_directory
from dotenv import load_dotenv
from PIL import Image

# 导入智能选择器和Stable Zero123
from utils.smart_selector import SmartEngineSelector, GenerationEngine
from utils.stable_3d_generator import Stable3DGenerator
from extensions import limiter

# 加载环境变量
load_dotenv()

world_bp = Blueprint('world', __name__)

# World Labs API 配置
API_KEY = os.environ.get('WORLD_LABS_API_KEY')
if not API_KEY:
    logging.warning(
        "⚠️ 缺少 WORLD_LABS_API_KEY 环境变量。"
        "World Labs 引擎将不可用，请在 .env 文件中设置。"
    )

API_URL = 'https://api.worldlabs.ai/marble/v1'

# 本地 LLM 配置
LM_STUDIO_URL = os.environ.get('LM_STUDIO_URL', 'http://localhost:1234/v1')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

# 允许的图片扩展名
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

# 混合3D生成器初始化
smart_selector = SmartEngineSelector()
stable_3d_generator = Stable3DGenerator()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

# 创建事件循环线程（用于处理异步操作）
asyncio_loop = None


def get_asyncio_loop():
    global asyncio_loop
    if asyncio_loop is None:
        asyncio_loop = asyncio.new_event_loop()
        thread = threading.Thread(
            target=lambda: asyncio_loop.run_forever(), daemon=True
        )
        thread.start()
    return asyncio_loop


# ===== 上传文件自动清理 =====
def cleanup_old_uploads(max_age_hours=1):
    """清理超过指定时长的上传文件"""
    now = datetime.now()
    cutoff = now - timedelta(hours=max_age_hours)
    cleaned = 0
    try:
        for filepath in Path(UPLOAD_DIR).iterdir():
            if filepath.is_file():
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                if mtime < cutoff:
                    filepath.unlink()
                    cleaned += 1
    except Exception as e:
        logging.debug(f"清理上传文件时出错: {e}")
    if cleaned:
        logging.info(f"已清理 {cleaned} 个过期上传文件")


def _cleanup_daemon(interval_seconds=3600):
    """后台守护线程，定期清理旧文件"""
    while True:
        time.sleep(interval_seconds)
        cleanup_old_uploads()


# 启动清理守护线程
threading.Thread(target=_cleanup_daemon, daemon=True).start()


# ===== 辅助函数 =====
def get_api_key_from_request():
    """从请求头获取 API Key（优先），回退到表单/JSON/查询参数"""
    # 优先从请求头获取
    key = request.headers.get('X-API-Key', '').strip()
    if key:
        return key
    # 回退：表单
    key = request.form.get('api_key', '').strip()
    if key:
        return key
    # 回退：JSON body
    if request.is_json:
        data = request.get_json(silent=True) or {}
        key = (data.get('api_key') or '').strip()
        if key:
            return key
    # 回退：查询参数
    key = request.args.get('api_key', '').strip()
    if key:
        return key
    return ''


def validate_image_file(image_file):
    """
    验证上传的文件是真正的图片。
    返回 (is_valid, error_message)
    """
    if not image_file or not image_file.filename:
        return False, '没有有效的图片文件'

    ext = os.path.splitext(image_file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, '只支持 JPG/PNG/WEBP 格式'

    # 用 Pillow 验证文件内容是否为真实图片
    try:
        img = Image.open(image_file.stream)
        img.verify()  # 验证但不加载像素数据
        # verify 后需要重新打开才能读取
        image_file.stream.seek(0)
    except Exception:
        return False, '文件不是有效的图片或已损坏'

    return True, None


def save_uploaded_image(image_file):
    """
    保存上传的图片并返回 (filepath, image_url)。
    调用前需先通过 validate_image_file 验证。
    """
    ext = os.path.splitext(image_file.filename)[1].lower()
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    image_file.save(filepath)
    image_url = f"{request.host_url}uploads/{filename}"
    return filepath, image_url


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
输出: A cute orange tabby cat sitting on a sunlit windowsill, soft morning light
streaming through lace curtains, warm cozy atmosphere, wooden window frame,
indoor plants nearby, photorealistic, soft shadows, golden hour lighting"""

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


# ===== create_world 拆分后的子函数 =====
def _parse_create_request():
    """
    解析 /create 请求参数。
    返回 dict: {prompt, use_local_llm, engine_preference, image_file, image_url}
    """
    result = {
        'prompt': '',
        'use_local_llm': True,
        'engine_preference': 'auto',
        'image_file': None,
        'image_url': None,
    }

    if request.content_type and 'multipart/form-data' in request.content_type:
        result['prompt'] = request.form.get('prompt', '')
        result['use_local_llm'] = (
            request.form.get('use_local_llm', 'true').lower() == 'true'
        )
        result['engine_preference'] = request.form.get('engine', 'auto')
        result['image_file'] = request.files.get('image')
    elif request.is_json:
        data = request.get_json()
        result['prompt'] = data.get('prompt', '')
        result['use_local_llm'] = data.get('use_local_llm', True)
        result['engine_preference'] = data.get('engine', 'auto')
        result['image_url'] = data.get('image_url')

    return result


def _enhance_prompt(prompt, use_local_llm):
    """
    使用本地 LLM 优化提示词。
    返回 (final_prompt, llm_used)
    """
    if not (use_local_llm and prompt):
        return prompt, None

    llm_type, llm_url = check_local_llm()
    if not llm_type:
        return prompt, None

    enhanced = enhance_prompt_with_local_llm(prompt, llm_type, llm_url)
    if enhanced:
        logging.info(f"使用 {llm_type} 优化提示词: {prompt} -> {enhanced}")
        return enhanced, llm_type

    return prompt, None


def _select_engine(final_prompt, has_image, engine_preference):
    """
    智能选择 3D 生成引擎。
    返回 selected_engine
    """
    try:
        loop = get_asyncio_loop()
        selection_result = loop.run_coroutine_threadsafe(
            smart_selector.select_best_engine(
                prompt=final_prompt,
                has_image=has_image,
                user_preference=engine_preference,
                urgency_level=2
            ), loop
        ).result(timeout=5.0)

        selected_engine = selection_result.selected_engine
        logging.info(
            f"智能引擎选择: {selected_engine.value} - "
            f"{selection_result.reasoning}"
        )
        return selected_engine

    except Exception as e:
        logging.warning(f"智能选择失败，使用默认引擎: {e}")
        return GenerationEngine.WORLD_LABS


def _handle_stable_3d(image_file, image_url, final_prompt):
    """
    处理 Stable Zero123 引擎的 3D 生成。
    返回 (response_json, status_code) 或 None 表示降级到 World Labs。
    """
    try:
        image_to_process = None
        saved_filepath = None

        if image_file:
            # 从已保存的文件路径读取（避免 stream 已消费的问题）
            saved_filepath = os.path.join(UPLOAD_DIR, _last_saved_filename)
            if os.path.exists(saved_filepath):
                image_to_process = Image.open(saved_filepath)
            else:
                image_to_process = Image.open(image_file.stream)
        elif image_url:
            return jsonify({
                'success': False,
                'error': 'Stable Zero123暂时不支持URL输入，请上传图片文件'
            }), 400

        if image_to_process:
            loop = get_asyncio_loop()
            stable_result = loop.run_coroutine_threadsafe(
                stable_3d_generator.generate_3d_from_image(
                    image_to_process,
                    final_prompt or "a 3D model"
                ), loop
            ).result(timeout=120.0)

            if stable_result.get('success'):
                return jsonify({
                    'success': True,
                    'engine_used': 'stable-zero123',
                    'generation_type': 'multi_view_3d',
                    'result': stable_result,
                    'task_id': f"stable3d_{uuid.uuid4().hex[:8]}",
                    'status': 'completed',
                    'message': '使用Stable Zero123生成了多视角3D视图'
                }), 200
            else:
                logging.warning(
                    f"Stable Zero123失败，降级到World Labs: "
                    f"{stable_result.get('error')}"
                )
                return None  # 降级

    except Exception as e:
        logging.error(f"Stable Zero123处理失败: {e}")
        return None  # 降级

    return None


def _handle_world_labs(final_prompt, prompt, llm_used, image_url, api_key):
    """
    处理 World Labs 引擎的 3D 生成。
    返回 (response_json, status_code)
    """
    headers = {
        'WLT-Api-Key': api_key,
        'Content-Type': 'application/json'
    }

    # 构建 world_prompt：优先图片，否则文本
    if image_url:
        world_prompt = {
            "type": "image_url",
            "image_url": {"url": image_url}
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

    logging.info(f"创建 3D 世界 (World Labs): prompt={final_prompt[:100]}...")
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
            'engine_used': 'world-labs',
            'task_id': result.get('operation_id'),
            'status': 'processing',
            'original_prompt': prompt,
            'enhanced_prompt': final_prompt if final_prompt != prompt else None,
            'llm_used': llm_used,
            'image_url': image_url
        }), 200
    else:
        logging.error(
            f"API 错误: {response.status_code} - {response.text[:200]}"
        )
        return jsonify({
            'success': False,
            'error': f'API 错误: {response.status_code}',
            'details': response.text[:1000]
        }), response.status_code


# 用于 Stable Zero123 读取已保存文件的文件名记录
_last_saved_filename = None


# ===== 路由 =====
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
@limiter.limit("10 per minute")
def upload_image():
    """上传图片，返回 URL"""
    try:
        if 'image' not in request.files and 'image' not in request.form:
            return jsonify({'success': False, 'error': '没有上传图片'}), 400

        image_file = request.files.get('image')
        is_valid, error_msg = validate_image_file(image_file)
        if not is_valid:
            return jsonify({'success': False, 'error': error_msg}), 400

        # 验证通过后重新 seek 并保存
        ext = os.path.splitext(image_file.filename)[1].lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        image_file.stream.seek(0)
        image_file.save(filepath)

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
@limiter.limit("5 per minute")
def create_world():
    """创建 3D 世界（支持智能引擎选择和图片上传）"""
    global _last_saved_filename
    try:
        # ========== 1. 解析请求参数 ==========
        params = _parse_create_request()
        prompt = params['prompt']
        use_local_llm = params['use_local_llm']
        engine_preference = params['engine_preference']
        image_file = params['image_file']
        image_url = params['image_url']

        # 处理上传图片
        if image_file and image_file.filename:
            is_valid, error_msg = validate_image_file(image_file)
            if not is_valid:
                return jsonify({
                    'success': False, 'error': error_msg
                }), 400
            # 验证通过后重新 seek 并保存
            image_file.stream.seek(0)
            saved_filepath, image_url = save_uploaded_image(image_file)
            _last_saved_filename = os.path.basename(saved_filepath)

        if not prompt and not image_url:
            return jsonify({
                'success': False, 'error': '请输入提示词或上传图片'
            }), 400

        # ========== 2. 本地 LLM 优化提示词 ==========
        final_prompt, llm_used = _enhance_prompt(prompt, use_local_llm)

        # ========== 3. 智能引擎选择 ==========
        has_image = bool(image_file or image_url)
        selected_engine = _select_engine(
            final_prompt, has_image, engine_preference
        )

        # ========== 4. Stable Zero123 引擎处理 ==========
        if selected_engine == GenerationEngine.STABLE_3D and has_image:
            result = _handle_stable_3d(image_file, image_url, final_prompt)
            if result is not None:
                # 补充额外字段
                resp_data = result[0].get_json()
                resp_data['original_prompt'] = prompt
                resp_data['enhanced_prompt'] = (
                    final_prompt if final_prompt != prompt else None
                )
                resp_data['llm_used'] = llm_used
                resp_data['image_url'] = image_url
                return jsonify(resp_data), result[1]
            # result is None → 降级到 World Labs
            selected_engine = GenerationEngine.WORLD_LABS

        # ========== 5. World Labs 引擎处理（默认/降级） ==========
        api_key = get_api_key_from_request() or API_KEY

        if not api_key:
            return jsonify({
                'success': False,
                'error': '缺少 World Labs API Key。请在请求头 X-API-Key 中传入或在 .env 中设置。'
            }), 401

        return _handle_world_labs(
            final_prompt, prompt, llm_used, image_url, api_key
        )

    except Exception as e:
        logging.error(f"创建世界失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/engine-status')
def engine_status():
    """获取3D生成引擎状态"""
    try:
        status_report = smart_selector.get_engine_status_report()
        statistics = smart_selector.get_selection_statistics()
        stable_3d_info = stable_3d_generator.get_model_info()

        return jsonify({
            'success': True,
            'report_generated_at': datetime.now().isoformat(),
            'engines': status_report,
            'selection_statistics': statistics,
            'stable_zero123_info': stable_3d_info,
            'message': '返回所有3D生成引擎的状态信息'
        })

    except Exception as e:
        logging.error(f"获取引擎状态失败: {e}")
        return jsonify({
            'success': False,
            'error': f'获取引擎状态失败: {e}'
        }), 500


@world_bp.route('/test-stable-3d', methods=['POST'])
def test_stable_3d():
    """测试Stable Zero123功能（开发用）"""
    try:
        if 'image' not in request.files:
            return jsonify({
                'success': False, 'error': '需要上传图片进行测试'
            }), 400

        image_file = request.files['image']
        prompt = request.form.get('prompt', 'a 3D model')

        image = Image.open(image_file.stream).convert('RGB')

        loop = get_asyncio_loop()
        result = loop.run_coroutine_threadsafe(
            stable_3d_generator.generate_3d_from_image(image, prompt, num_views=2),
            loop
        ).result(timeout=60.0)

        return jsonify({
            'success': True,
            'test_result': result,
            'message': 'Stable Zero123测试完成'
        })

    except Exception as e:
        logging.error(f"Stable Zero123测试失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@world_bp.route('/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """获取任务状态"""
    try:
        api_key = get_api_key_from_request() or API_KEY

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
            logging.error(
                f"获取状态失败: {response.status_code} - {response.text[:200]}"
            )
            return jsonify({
                'success': False,
                'error': f'获取状态失败: {response.status_code}'
            }), response.status_code

    except Exception as e:
        logging.error(f"查询任务状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
