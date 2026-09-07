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
from flask import Blueprint, request, jsonify, Response
from dotenv import load_dotenv
from PIL import Image

# 导入智能选择器、Stable Zero123 和文生图
from utils.smart_selector import SmartEngineSelector, GenerationEngine
from utils.stable_3d_generator import Stable3DGenerator
from utils.text_to_image import TextToImageGenerator
from utils.local_llm import LocalLLMClient
from utils import history_store
from extensions import limiter

# 加载环境变量
load_dotenv()

world_bp = Blueprint('world', __name__)

# 日志（配置由 app.py 统一完成）
logger = logging.getLogger(__name__)

# World Labs API 配置
API_KEY = os.environ.get('WORLD_LABS_API_KEY')
if not API_KEY:
    logger.warning(
        "⚠️ 缺少 WORLD_LABS_API_KEY 环境变量。"
        "World Labs 引擎将不可用，请在 .env 文件中设置。"
    )

API_URL = 'https://api.worldlabs.ai/marble/v1'

# World Labs Marble 模型（World API 规范）
WORLD_LABS_MODELS = [
    'marble-1.0-draft',   # 快速/低成本草稿
    'marble-1.0',
    'marble-1.1',         # 默认，支持全景输入
    'marble-1.1-plus',    # 动态世界尺寸
]
WORLD_LABS_MODEL = os.environ.get('WORLD_LABS_MODEL', 'marble-1.1')

# Atlas（World Labs 新一代全模世界模型）：暂无公开 API，仅早期合作伙伴。
# 引擎位已预留，待 World Labs 公开 Atlas API 后在此接入。
ATLAS_ENGINE_RESERVED = True

# 上传目录（与 app.py 一致：项目根目录/uploads/）
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
# Stable Zero123 多视角输出目录
GENERATED_3D_DIR = os.path.join(os.path.dirname(__file__), '..', 'generated_3d_views')

# 允许的图片扩展名
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

# 混合3D生成器初始化
smart_selector = SmartEngineSelector()
stable_3d_generator = Stable3DGenerator()
text_to_image_generator = TextToImageGenerator()

# 通用本地 LLM 客户端（LM Studio / vLLM / llama.cpp / Ollama / 任意 OpenAI 兼容端点）
llm_client = LocalLLMClient()

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
    """清理超过指定时长的上传文件（历史画廊引用的文件豁免）"""
    now = datetime.now()
    cutoff = now - timedelta(hours=max_age_hours)
    cleaned = 0
    try:
        referenced = history_store.referenced_files()
        for filepath in Path(UPLOAD_DIR).iterdir():
            if filepath.is_file():
                if filepath.name in referenced:
                    continue  # 画廊引用，跳过清理
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                if mtime < cutoff:
                    filepath.unlink()
                    cleaned += 1
    except Exception as e:
        logger.debug(f"清理上传文件时出错: {e}")
    if cleaned:
        logger.info(f"已清理 {cleaned} 个过期上传文件")


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
    image_url = f"/uploads/{filename}"
    return filepath, image_url


# ===== create_world 拆分后的子函数 =====
def _parse_create_request():
    """
    解析 /create 请求参数。
    返回 dict: {prompt, use_local_llm, engine_preference, image_file, image_url,
                llm_model, three_d_backend}
    """
    result = {
        'prompt': '',
        'use_local_llm': True,
        'engine_preference': 'stable_3d',
        'image_file': None,
        'image_url': None,
        'llm_model': '',
        'three_d_backend': '',
        'world_model': '',
        'is_pano': '',
        'seed': None,
        'image_files': [],
        'video_file': None,
        'reconstruct': False,
    }

    if request.content_type and 'multipart/form-data' in request.content_type:
        result['prompt'] = request.form.get('prompt', '')
        result['use_local_llm'] = (
            request.form.get('use_local_llm', 'true').lower() == 'true'
        )
        result['engine_preference'] = request.form.get('engine', 'auto')
        result['image_file'] = request.files.get('image')
        result['image_url'] = request.form.get('image_url')
        result['llm_model'] = request.form.get('llm_model', '').strip()
        result['three_d_backend'] = request.form.get('three_d_backend', '').strip()
        result['world_model'] = request.form.get('world_model', '').strip()
        result['is_pano'] = request.form.get('is_pano', '').strip().lower()
        raw_seed = request.form.get('seed', '').strip()
        if raw_seed.isdigit():
            result['seed'] = int(raw_seed)
        # 多模态输入（World Labs 专属）
        result['image_files'] = [
            f for f in request.files.getlist('images') if f and f.filename
        ]
        result['video_file'] = request.files.get('video')
        result['reconstruct'] = (
            request.form.get('reconstruct_images', 'true').lower() == 'true'
        )
    elif request.is_json:
        data = request.get_json(silent=True) or {}
        result['prompt'] = data.get('prompt', '')
        result['use_local_llm'] = data.get('use_local_llm', True)
        result['engine_preference'] = data.get('engine', 'auto')
        result['image_url'] = data.get('image_url')
        result['llm_model'] = (data.get('llm_model') or '').strip()
        result['three_d_backend'] = (data.get('three_d_backend') or '').strip()
        result['world_model'] = (data.get('world_model') or '').strip()
        result['is_pano'] = str(data.get('is_pano') or '').strip().lower()
        seed = data.get('seed')
        if isinstance(seed, int) and 0 <= seed <= 4294967295:
            result['seed'] = seed

    return result


def _enhance_prompt(prompt, use_local_llm, llm_model=None):
    """
    使用本地 LLM 优化提示词。
    返回 (final_prompt, llm_used)
    """
    if not (use_local_llm and prompt):
        return prompt, None

    enhanced, llm_used = llm_client.enhance_prompt(
        prompt, model_override=llm_model or None
    )
    if enhanced:
        logger.info(f"使用 {llm_used} 优化提示词: {prompt} -> {enhanced}")
        return enhanced, llm_used

    return prompt, None


def _select_engine(final_prompt, has_image, engine_preference):
    """
    智能选择 3D 生成引擎。
    返回 selected_engine
    """
    try:
        selection_result = smart_selector.select_best_engine(
            prompt=final_prompt,
            has_image=has_image,
            user_preference=engine_preference,
            urgency_level=2
        )

        selected_engine = selection_result.selected_engine
        logger.info(
            f"智能引擎选择: {selected_engine.value} - "
            f"{selection_result.reasoning}"
        )
        return selected_engine

    except Exception as e:
        logger.warning(f"智能选择失败，使用默认引擎: {e}")
        return GenerationEngine.STABLE_3D


def _handle_stable_3d(image_to_process, final_prompt, backend=None):
    """
    处理 Stable Zero123 系引擎的 3D 生成。
    image_to_process: PIL.Image 对象（由调用方传入）
    backend: three_d_backend 请求参数（None 表示使用服务端默认）
    返回 dict: {success, data, status_code} 或 None 表示降级到 World Labs
    """
    if image_to_process is None:
        logger.warning("Stable Zero123 需要图片输入，但未传入")
        return None

    try:
        loop = get_asyncio_loop()
        stable_result = asyncio.run_coroutine_threadsafe(
            stable_3d_generator.generate_3d_from_image(
                image_to_process,
                final_prompt or "a 3D model",
                backend=backend or None
            ), loop
        ).result(timeout=600.0)

        if stable_result.get('success'):
            return {
                'success': True,
                'data': {
                    'engine_used': 'stable-zero123',
                    'generation_type': 'multi_view_3d',
                    'result': stable_result,
                    'task_id': f"stable3d_{uuid.uuid4().hex[:8]}",
                    'status': 'completed',
                    'message': '使用Stable Zero123生成了多视角3D视图'
                },
                'status_code': 200
            }
        else:
            logger.warning(
                f"Stable Zero123失败，降级到World Labs: "
                f"{stable_result.get('error')}"
            )
            return None  # 降级

    except Exception as e:
        logger.error(f"Stable Zero123处理失败: {e}")
        return None  # 降级


def _upload_media_asset(file_path, api_key, kind='image'):
    """将本地图片/视频上传为 World Labs Media Asset（官方三步流程）。

    1. POST /media-assets:prepare_upload 获取 media_asset_id + 签名上传 URL
    2. PUT 文件字节到签名 URL（带 required_headers）
    3. 返回 media_asset_id 供 worlds:generate 引用

    本地服务的 /uploads/ 图片无公网 URL，必须走此流程。
    """
    headers = {'WLT-Api-Key': api_key, 'Content-Type': 'application/json'}
    file_name = os.path.basename(file_path)
    extension = os.path.splitext(file_name)[1].lstrip('.').lower() or 'png'

    resp = requests.post(
        f'{API_URL}/media-assets:prepare_upload',
        headers=headers,
        json={'file_name': file_name, 'extension': extension, 'kind': kind},
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f'Media Asset 准备失败: HTTP {resp.status_code} - {resp.text[:300]}'
        )

    data = resp.json()
    media_asset_id = data['media_asset']['media_asset_id']
    upload_info = data['upload_info']
    upload_url = upload_info['upload_url']
    required_headers = upload_info.get('required_headers') or {}

    with open(file_path, 'rb') as f:
        file_bytes = f.read()
    upload_resp = requests.put(
        upload_url, data=file_bytes, headers=required_headers, timeout=120
    )
    if upload_resp.status_code not in (200, 201):
        raise RuntimeError(
            f'Media Asset 上传失败: HTTP {upload_resp.status_code}'
        )

    logger.info(f"Media Asset 上传成功: {media_asset_id}")
    return media_asset_id


def _generate_world_multimodal(final_prompt, prompt, llm_used, api_key,
                               image_files=None, video_file=None,
                               reconstruct=False, world_model=None, seed=None):
    """多图 / 视频输入生成世界（World API multi-image / video 模态）。

    image_files: 2-8 个本地图片路径（方位角自动均分）
    video_file:  本地视频路径
    返回 (response_json, status_code)
    """
    headers = {
        'WLT-Api-Key': api_key,
        'Content-Type': 'application/json',
    }
    model = world_model if world_model in WORLD_LABS_MODELS else WORLD_LABS_MODEL

    try:
        if video_file:
            media_asset_id = _upload_media_asset(video_file, api_key, kind='video')
            world_prompt = {
                'type': 'video',
                'video_prompt': {
                    'source': 'media_asset',
                    'media_asset_id': media_asset_id,
                },
            }
            if final_prompt:
                world_prompt['text_prompt'] = final_prompt
        else:
            count = len(image_files)
            step = 360 / count
            items = []
            for i, path in enumerate(image_files):
                media_asset_id = _upload_media_asset(path, api_key, kind='image')
                items.append({
                    'content': {
                        'source': 'media_asset',
                        'media_asset_id': media_asset_id,
                    },
                    'azimuth': round(i * step, 1),
                })
            world_prompt = {
                'type': 'multi-image',
                'multi_image_prompt': items,
                'reconstruct_images': bool(reconstruct),
            }
            if final_prompt:
                world_prompt['text_prompt'] = final_prompt
    except RuntimeError as e:
        logger.error(f"Media Asset 上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 502

    payload = {
        'display_name': (final_prompt or 'Multi-image World')[:64] or 'My World',
        'model': model,
        'world_prompt': world_prompt,
    }
    if seed is not None:
        payload['seed'] = seed

    logger.info(
        f"创建 3D 世界 (World Labs/{model}, "
        f"{'video' if video_file else f'multi-image x{len(image_files)}'})"
    )
    response = requests.post(
        f'{API_URL}/worlds:generate',
        headers=headers,
        json=payload,
        timeout=30,
    )
    if response.status_code in [200, 201]:
        result = response.json()
        operation_id = result.get('operation_id')
        logger.info(f"任务创建成功: task_id={operation_id}")
        # 登记历史（轮询完成时回填）
        try:
            history_store.record(
                kind='world',
                prompt=prompt,
                engine=f'world-labs ({model})',
                status='processing',
                task_id=operation_id,
                payload={'model': model,
                         'input_type': 'video' if video_file else 'multi-image'},
            )
        except Exception as he:
            logger.warning(f"记录历史失败: {he}")
        return jsonify({
            'success': True,
            'engine_used': f'world-labs ({model})',
            'task_id': operation_id,
            'status': 'processing',
            'original_prompt': prompt,
            'enhanced_prompt': final_prompt if final_prompt != prompt else None,
            'llm_used': llm_used,
        }), 200

    logger.error(f"API 错误: {response.status_code} - {response.text[:200]}")
    return jsonify({
        'success': False,
        'error': f'API 错误: {response.status_code}',
        'details': response.text[:1000],
    }), response.status_code


def _handle_world_labs(final_prompt, prompt, llm_used, image_url,
                       api_key, saved_filepath=None, world_model=None,
                       is_pano=None, seed=None):
    """
    处理 World Labs 引擎的 3D 生成（World API 规范格式）。
    返回 (response_json, status_code)
    """
    headers = {
        'WLT-Api-Key': api_key,
        'Content-Type': 'application/json'
    }

    # 构建 world_prompt：优先图片，否则文本
    if image_url:
        image_prompt = {}
        if image_url.startswith(('http://', 'https://')):
            # 公网 URL 直接引用
            image_prompt = {'source': 'uri', 'uri': image_url}
        else:
            # 本地 /uploads/ 图片 → media asset 三步上传
            local_path = saved_filepath
            if not local_path:
                filename = os.path.basename(image_url)
                local_path = os.path.join(UPLOAD_DIR, filename)
            if not os.path.exists(local_path):
                return jsonify({
                    'success': False,
                    'error': f'本地图片不存在: {local_path}'
                }), 400
            try:
                media_asset_id = _upload_media_asset(local_path, api_key)
            except RuntimeError as e:
                logger.error(f"Media Asset 上传失败: {e}")
                return jsonify({
                    'success': False, 'error': str(e)
                }), 502
            image_prompt = {
                'source': 'media_asset',
                'media_asset_id': media_asset_id,
            }

        world_prompt = {
            'type': 'image',
            'image_prompt': image_prompt,
        }
        if final_prompt and final_prompt != prompt:
            world_prompt['text_prompt'] = final_prompt
        if is_pano in ('auto', 'true', 'false'):
            world_prompt['is_pano'] = is_pano
    else:
        world_prompt = {
            "type": "text",
            "text_prompt": final_prompt
        }

    model = world_model if world_model in WORLD_LABS_MODELS else WORLD_LABS_MODEL
    payload = {
        "display_name": (final_prompt or "Image World")[:64] or "My World",
        "model": model,
        "world_prompt": world_prompt,
    }
    if seed is not None:
        payload['seed'] = seed

    logger.info(
        f"创建 3D 世界 (World Labs/{model}): prompt={final_prompt[:100]}..."
    )
    response = requests.post(
        f'{API_URL}/worlds:generate',
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code in [200, 201]:
        result = response.json()
        logger.info(f"任务创建成功: task_id={result.get('operation_id')}")
        # 登记历史（轮询完成时回填 world 结果）
        try:
            history_store.record(
                kind='world',
                prompt=prompt,
                engine=f'world-labs ({model})',
                status='processing',
                task_id=result.get('operation_id'),
                payload={
                    'image_url': image_url,
                    'model': model,
                },
                files=[image_url] if (image_url and image_url.startswith('/uploads/')) else [],
            )
        except Exception as he:
            logger.warning(f"记录历史失败: {he}")
        return jsonify({
            'success': True,
            'engine_used': f'world-labs ({model})',
            'task_id': result.get('operation_id'),
            'status': 'processing',
            'original_prompt': prompt,
            'enhanced_prompt': final_prompt if final_prompt != prompt else None,
            'llm_used': llm_used,
            'image_url': image_url
        }), 200
    else:
        logger.error(
            f"API 错误: {response.status_code} - {response.text[:200]}"
        )
        return jsonify({
            'success': False,
            'error': f'API 错误: {response.status_code}',
            'details': response.text[:1000]
        }), response.status_code


# ===== 路由 =====
@world_bp.route('/llm-status', methods=['GET'])
def get_llm_status():
    """获取本地 LLM 状态"""
    try:
        info = llm_client.detect()
        if info['available']:
            return jsonify({
                'success': True,
                'available': True,
                'type': info['provider'],
                'url': info['base_url'],
                'model': info['model'],
                'models': info['models'],
            })
        return jsonify({
            'success': True,
            'available': False,
            'message': info.get(
                'reason',
                '未检测到本地 LLM。请启动 LM Studio / Ollama / vLLM 等本地服务，'
                '或通过 LLM_BASE_URL 指定任意 OpenAI 兼容端点。'
            )
        })
    except Exception as e:
        logger.error(f"检查 LLM 状态失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@world_bp.route('/models', methods=['GET'])
def list_models():
    """列出可用的本地部署模型（LLM / 文生图 / 3D 生成）"""
    try:
        llm_info = llm_client.detect()
        t2i_info = text_to_image_generator.get_info()
        stable_3d_info = stable_3d_generator.get_model_info()

        return jsonify({
            'success': True,
            'llm': {
                'available': llm_info['available'],
                'provider': llm_info.get('provider'),
                'model': llm_info.get('model'),
                'models': llm_info.get('models', []),
            },
            'text_to_image': {
                'available': t2i_info.get('is_loaded') or True,
                'model': t2i_info.get('model_id'),
                'models': text_to_image_generator.get_available_models(),
                'pipeline': t2i_info.get('pipeline'),
                'default_params': text_to_image_generator.get_default_params(),
            },
            'three_d': {
                'available': True,
                'backend': stable_3d_info.get('effective_backend')
                or stable_3d_info.get('configured_backend'),
                'available_backends': stable_3d_info.get('available_backends', []),
                'device': stable_3d_info.get('device'),
            },
            'worldlabs': {
                'available': bool(API_KEY),
                'model': WORLD_LABS_MODEL,
                'models': WORLD_LABS_MODELS,
                'features': [
                    'text', 'image', 'pano', 'multi-image', 'video',
                    'seed', 'tags', 'media_asset_upload', 'ply_export',
                ],
            },
            'atlas': {
                'available': False,
                'reserved': ATLAS_ENGINE_RESERVED,
                'note': 'Atlas（World Labs 全模世界模型）暂无公开 API，'
                        '仅限早期合作伙伴。引擎位已预留，待公开后接入。'
                        '可到 worldlabs.ai 申请早期访问。',
                'capabilities': [
                    'camera-controlled 1440p video (up to 1min)',
                    'sparse-image 3D reconstruction',
                    'point clouds / Gaussian splats',
                ],
            },
        })
    except Exception as e:
        logger.error(f"获取模型列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/splat-ply/<world_id>', methods=['GET'])
def get_splat_ply(world_id):
    """代理下载世界的高斯点云 PLY（供网页 3D 查看器加载）。

    内部流程：调用 :export（SPZ→PLY 转换，通常立即完成）→
    拿到签名 URL → 流式转发 PLY 字节给前端（规避签名过期与跨域）。
    """
    try:
        api_key = get_api_key_from_request() or API_KEY
        if not api_key:
            return jsonify({'success': False, 'error': '缺少 World Labs API Key'}), 401

        headers = {
            'WLT-Api-Key': api_key,
            'Content-Type': 'application/json',
        }
        export_resp = requests.post(
            f'{API_URL}/worlds/{world_id}:export',
            headers=headers,
            json={'asset_type': 'splats', 'format': 'ply',
                  'resolution': 'full_res'},
            timeout=60,
        )
        if export_resp.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'导出失败: HTTP {export_resp.status_code}',
            }), export_resp.status_code

        operation = export_resp.json()
        download_url = (operation.get('response') or {}).get('url')

        # PLY 转换通常立即完成；未完成则轮询 operation（最多 ~120s）
        waited = 0
        while not download_url and not operation.get('done') and waited < 120:
            time.sleep(3)
            waited += 3
            op_resp = requests.get(
                f'{API_URL}/operations/{operation.get("operation_id")}',
                headers={'WLT-Api-Key': api_key},
                timeout=30,
            )
            if op_resp.status_code == 200:
                operation = op_resp.json()
                download_url = (operation.get('response') or {}).get('url')

        if not download_url:
            return jsonify({
                'success': False, 'error': 'PLY 导出超时，请稍后重试'
            }), 504

        # 流式转发 PLY 字节
        upstream = requests.get(download_url, stream=True, timeout=120)
        if upstream.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'PLY 下载失败: HTTP {upstream.status_code}',
            }), 502

        def stream():
            for chunk in upstream.iter_content(chunk_size=1024 * 256):
                if chunk:
                    yield chunk

        return Response(
            stream(),
            content_type='application/octet-stream',
            headers={'Content-Disposition':
                     f'inline; filename="{world_id}.ply"'},
        )
    except Exception as e:
        logger.error(f"PLY 代理失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/history', methods=['GET'])
def get_history():
    """分页获取生成历史"""
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        offset = max(int(request.args.get('offset', 0)), 0)
    except ValueError:
        return jsonify({'success': False, 'error': 'limit/offset 必须是整数'}), 400
    try:
        data = history_store.list_entries(limit=limit, offset=offset)
        return jsonify({'success': True, **data})
    except Exception as e:
        logger.error(f"获取历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/history/<entry_id>', methods=['DELETE'])
def delete_history(entry_id):
    """删除一条历史记录（默认同时删除其引用的生成文件）"""
    try:
        delete_files = request.args.get('delete_files', 'true').lower() != 'false'
        removed = history_store.delete_entry(entry_id, delete_files=delete_files)
        if not removed:
            return jsonify({'success': False, 'error': '记录不存在'}), 404
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"删除历史失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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

        # 复用通用保存函数
        image_file.stream.seek(0)
        filepath, image_url = save_uploaded_image(image_file)
        filename = os.path.basename(filepath)

        logger.info(f"图片上传成功: {filename}")
        return jsonify({
            'success': True,
            'url': image_url,
            'filename': filename
        })

    except Exception as e:
        logger.error(f"图片上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


def _parse_generate_image_params():
    """解析 /generate-image 的请求参数（multipart 与 JSON 通用）"""
    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form

    params = {
        'prompt': (data.get('prompt') or '').strip(),
        'model': (data.get('model') or '').strip() or None,
    }

    def _int_field(name, default):
        raw = data.get(name)
        if raw in (None, ''):
            return default, None
        try:
            return int(raw), None
        except (TypeError, ValueError):
            return default, f'参数 {name} 必须是整数'

    for key in ('width', 'height'):
        params[key], err = _int_field(key, None)
        if err:
            return params, err
    params['num_inference_steps'], err = _int_field('num_inference_steps', None)
    if err:
        return params, err
    return params, None


def _validate_generate_image_params(params):
    """校验文生图参数，返回 error 字符串或 None"""
    if not params['prompt']:
        return '请输入提示词'

    for key, lo, hi in (
        ('width', 256, 1024),
        ('height', 256, 1024),
        ('num_inference_steps', 1, 60),
    ):
        value = params[key]
        if value is not None and not (lo <= value <= hi):
            return f'参数 {key} 超出范围 [{lo}, {hi}]'
    # SD 要求宽高为 8 的倍数
    for key in ('width', 'height'):
        value = params[key]
        if value is not None and value % 8 != 0:
            return f'参数 {key} 必须是 8 的倍数'
    return None


@world_bp.route('/generate-image', methods=['POST'])
@limiter.limit("5 per minute")
def generate_image():
    """使用本地 Stable Diffusion / SDXL 从文本提示词生成图片"""
    try:
        params, parse_err = _parse_generate_image_params()
        if parse_err:
            return jsonify({'success': False, 'error': parse_err}), 400

        validation_err = _validate_generate_image_params(params)
        if validation_err:
            return jsonify({'success': False, 'error': validation_err}), 400

        logger.info(
            f"文生图请求: {params['prompt'][:100]} "
            f"(model={params['model']}, {params['width']}x{params['height']}, "
            f"steps={params['num_inference_steps']})"
        )

        result = text_to_image_generator.generate_image(
            prompt=params['prompt'],
            model_id=params['model'],
            width=params['width'],
            height=params['height'],
            num_inference_steps=params['num_inference_steps'],
        )

        if result.get('success'):
            # 记录生成历史（画廊用）
            try:
                history_store.record(
                    kind='t2i',
                    prompt=result.get('prompt', ''),
                    engine=result.get('model', ''),
                    payload={
                        'image_url': result.get('image_url'),
                        'size': result.get('size'),
                        'generation_time': result.get('generation_time'),
                        'model': result.get('model'),
                    },
                    files=[result.get('image_url') or ''],
                )
            except Exception as he:
                logger.warning(f"记录历史失败: {he}")
            return jsonify(result), 200
        else:
            return jsonify(result), 500

    except Exception as e:
        logger.error(f"文生图失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@world_bp.route('/create', methods=['POST'])
@limiter.limit("5 per minute")
def create_world():
    """创建 3D 世界（支持智能引擎选择和图片上传）"""
    try:
        # ========== 1. 解析请求参数 ==========
        params = _parse_create_request()
        prompt = params['prompt']
        use_local_llm = params['use_local_llm']
        engine_preference = params['engine_preference']
        image_file = params['image_file']
        image_url = params['image_url']
        saved_filepath = None  # 跟踪保存的文件路径

        # ========== 1.5 多模态输入（多图 / 视频，走 World Labs） ==========
        if params['image_files'] or params['video_file']:
            api_key_early = get_api_key_from_request() or API_KEY
            if not api_key_early:
                return jsonify({
                    'success': False,
                    'error': '多图/视频输入需要 World Labs API Key（X-API-Key 或 .env）'
                }), 401

            if not prompt and not params['image_files'] and not params['video_file']:
                return jsonify({
                    'success': False, 'error': '请输入提示词或上传素材'
                }), 400

            saved_paths = []
            if params['video_file']:
                video = params['video_file']
                ext = os.path.splitext(video.filename)[1].lstrip('.').lower()
                if ext not in ('mp4', 'webm', 'mov', 'avi'):
                    return jsonify({
                        'success': False,
                        'error': '视频仅支持 mp4/webm/mov/avi 格式'
                    }), 400
                video.stream.seek(0)
                vpath = os.path.join(
                    UPLOAD_DIR, f"video_{uuid.uuid4().hex[:12]}.{ext}"
                )
                video.save(vpath)
                saved_paths = [vpath]
            else:
                if not (2 <= len(params['image_files']) <= 8):
                    return jsonify({
                        'success': False,
                        'error': '多图模式需要 2-8 张图片'
                    }), 400
                for img in params['image_files']:
                    is_valid, error_msg = validate_image_file(img)
                    if not is_valid:
                        return jsonify({
                            'success': False, 'error': f'{img.filename}: {error_msg}'
                        }), 400
                    img.stream.seek(0)
                    ext = os.path.splitext(img.filename)[1].lower() or '.png'
                    ipath = os.path.join(
                        UPLOAD_DIR, f"multi_{uuid.uuid4().hex[:12]}{ext}"
                    )
                    img.save(ipath)
                    saved_paths.append(ipath)

            # ========== 本地 LLM 优化提示词 ==========
            final_prompt, llm_used = _enhance_prompt(
                prompt, use_local_llm, llm_model=params['llm_model']
            )

            if params['video_file']:
                return _generate_world_multimodal(
                    final_prompt, prompt, llm_used, api_key_early,
                    video_file=saved_paths[0],
                    world_model=params['world_model'] or None,
                    seed=params['seed'],
                )
            return _generate_world_multimodal(
                final_prompt, prompt, llm_used, api_key_early,
                image_files=saved_paths,
                reconstruct=params['reconstruct'],
                world_model=params['world_model'] or None,
                seed=params['seed'],
            )

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

        if not prompt and not image_url:
            return jsonify({
                'success': False, 'error': '请输入提示词或上传图片'
            }), 400

        # ========== 2. 本地 LLM 优化提示词 ==========
        final_prompt, llm_used = _enhance_prompt(
            prompt, use_local_llm, llm_model=params['llm_model']
        )

        # ========== 3. 智能引擎选择 ==========
        has_image = bool(image_file or image_url)
        selected_engine = _select_engine(
            final_prompt, has_image, engine_preference
        )

        # ========== 4. Stable Zero123 引擎处理 ==========
        image_to_process = None
        if selected_engine == GenerationEngine.STABLE_3D and has_image:
            # 准备图片
            if saved_filepath and os.path.exists(saved_filepath):
                image_to_process = Image.open(saved_filepath)
            elif image_url and image_url.startswith('/uploads/'):
                local_filename = image_url.replace('/uploads/', '', 1)
                local_path = os.path.join(UPLOAD_DIR, local_filename)
                if os.path.exists(local_path):
                    image_to_process = Image.open(local_path)

            result = _handle_stable_3d(
                image_to_process, final_prompt, backend=params['three_d_backend']
            )
            if result and result['success']:
                # 补充额外字段
                resp_data = result['data']
                resp_data['original_prompt'] = prompt
                resp_data['enhanced_prompt'] = (
                    final_prompt if final_prompt != prompt else None
                )
                resp_data['llm_used'] = llm_used
                resp_data['image_url'] = image_url
                # 记录生成历史（画廊用）
                try:
                    stable_result = resp_data.get('result', {})
                    history_store.record(
                        kind='three_d',
                        prompt=prompt,
                        engine=stable_result.get('backend', 'stable-zero123'),
                        payload={
                            'image_url': image_url,
                            'view_urls': stable_result.get('view_urls', []),
                            'backend': stable_result.get('backend'),
                            'view_count': stable_result.get('view_count'),
                            'generation_time': stable_result.get('generation_time'),
                        },
                        files=(stable_result.get('view_urls') or [])
                        + ([image_url] if image_url else []),
                    )
                except Exception as he:
                    logger.warning(f"记录历史失败: {he}")
                return jsonify(resp_data), result['status_code']
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
            final_prompt, prompt, llm_used, image_url, api_key,
            saved_filepath=saved_filepath,
            world_model=params['world_model'] or None,
            is_pano=params['is_pano'] or None,
            seed=params['seed'],
        )

    except Exception as e:
        logger.error(f"创建世界失败: {e}")
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
        logger.error(f"获取引擎状态失败: {e}")
        return jsonify({
            'success': False,
            'error': f'获取引擎状态失败: {e}'
        }), 500


@world_bp.route('/credits')
def get_credits():
    """查询 World Labs API 剩余 credits"""
    try:
        api_key = get_api_key_from_request() or API_KEY
        if not api_key:
            return jsonify({
                'success': False, 'error': '缺少 World Labs API Key'
            }), 401

        response = requests.get(
            f'{API_URL}/credits',
            headers={'WLT-Api-Key': api_key},
            timeout=30
        )
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'查询失败: HTTP {response.status_code}'
            }), response.status_code

        remaining = response.json().get('remaining_credits')
        return jsonify({
            'success': True,
            'remaining_credits': remaining,
        })
    except Exception as e:
        logger.error(f"查询 credits 失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/export-orbit-video', methods=['POST'])
@limiter.limit("10 per minute")
def export_orbit_video():
    """把多视角图片合成为环绕展示视频（ping-pong mp4）

    请求体: {view_urls: ['/generated_3d_views/view_x.png', ...], fps?: 8, hold?: 2}
    返回: {success, video_url}
    """
    try:
        data = request.get_json(silent=True) or {}
        view_urls = data.get('view_urls') or []
        if not isinstance(view_urls, list) or not (2 <= len(view_urls) <= 16):
            return jsonify({
                'success': False,
                'error': 'view_urls 必须是 2-16 个视角图片路径的数组'
            }), 400
        try:
            fps = int(data.get('fps') or 8)
            hold = int(data.get('hold') or 2)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'fps/hold 必须是整数'}), 400
        if not (4 <= fps <= 30) or not (1 <= hold <= 6):
            return jsonify({
                'success': False, 'error': 'fps 取值 [4,30]，hold 取值 [1,6]'
            }), 400

        import imageio.v2 as imageio

        # 按序读取视角（支持 /generated_3d_views/ 与 /uploads/ 相对路径）
        frames = []
        for rel in view_urls:
            rel = (rel or '').lstrip('/')
            if rel.startswith('generated_3d_views/'):
                path = os.path.join(GENERATED_3D_DIR, rel[len('generated_3d_views/'):])
            elif rel.startswith('uploads/'):
                path = os.path.join(UPLOAD_DIR, rel[len('uploads/'):])
            elif rel.startswith('/uploads/'):
                path = os.path.join(UPLOAD_DIR, rel[len('/uploads/'):])
            else:
                return jsonify({
                    'success': False, 'error': f'不支持的视频帧路径: {rel}'
                }), 400
            if not os.path.exists(path):
                return jsonify({
                    'success': False, 'error': f'视角文件不存在: {rel}'
                }), 404
            frames.append(imageio.imread(path))

        # ping-pong 序列（正向 + 回放，循环播放无跳变），每视角停留 hold 帧
        sequence = frames + frames[-2:0:-1]
        tiled = []
        for img in sequence:
            tiled.extend([img] * hold)

        filename = f"orbit_{uuid.uuid4().hex[:12]}.mp4"
        filepath = os.path.join(UPLOAD_DIR, filename)
        imageio.mimwrite(filepath, tiled, fps=fps, codec='libx264',
                         quality=8, pixelformat='yuv420p')

        video_url = f"/uploads/{filename}"
        logger.info(f"环绕视频合成完成: {filename} ({len(tiled)} 帧)")
        try:
            history_store.record(
                kind='orbit_video',
                prompt='环绕视频导出',
                engine='imageio',
                payload={'video_url': video_url, 'view_urls': view_urls,
                         'frames': len(tiled), 'fps': fps},
                files=[video_url],
            )
        except Exception as he:
            logger.warning(f"记录历史失败: {he}")

        return jsonify({
            'success': True,
            'video_url': video_url,
            'frames': len(tiled),
            'fps': fps,
            'duration': round(len(tiled) / fps, 2),
        })
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'缺少视频合成依赖 (imageio/ffmpeg): {e}'
        }), 503
    except Exception as e:
        logger.error(f"环绕视频合成失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/export-world/<world_id>', methods=['POST'])
@limiter.limit("5 per minute")
def export_world(world_id):
    """导出世界资产：splats → PLY / mesh → GLB（World Labs :export 端点）"""
    try:
        api_key = get_api_key_from_request() or API_KEY
        if not api_key:
            return jsonify({
                'success': False, 'error': '缺少 World Labs API Key'
            }), 401

        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form or {}

        asset_type = (data.get('asset_type') or 'splats').strip()
        if asset_type not in ('splats', 'mesh'):
            return jsonify({
                'success': False, 'error': "asset_type 必须是 'splats' 或 'mesh'"
            }), 400

        payload = {'asset_type': asset_type}
        if asset_type == 'splats':
            fmt = (data.get('format') or 'ply').strip()
            if fmt != 'ply':
                return jsonify({
                    'success': False, 'error': "splats 导出仅支持 ply 格式"
                }), 400
            payload['format'] = 'ply'
            payload['resolution'] = (data.get('resolution') or 'full_res').strip()
        else:
            payload['format'] = 'glb'

        logger.info(
            f"导出世界资产: world={world_id}, {payload['asset_type']}"
        )
        response = requests.post(
            f'{API_URL}/worlds/{world_id}:export',
            headers={
                'WLT-Api-Key': api_key,
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=60,
        )
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'导出失败: HTTP {response.status_code}',
                'details': response.text[:500],
            }), response.status_code

        result = response.json()
        done = result.get('done', False)
        export_resp = result.get('response') or {}
        download_url = export_resp.get('url', '')

        return jsonify({
            'success': True,
            'done': done,
            'operation_id': result.get('operation_id'),
            'download_url': download_url,
            'message': (
                '导出完成' if done and download_url
                else '导出处理中，请稍后用 operation_id 查询'
            ),
        })
    except Exception as e:
        logger.error(f"导出世界资产失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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
        result = asyncio.run_coroutine_threadsafe(
            stable_3d_generator.generate_3d_from_image(image, prompt, num_views=2),
            loop
        ).result(timeout=60.0)

        return jsonify({
            'success': True,
            'test_result': result,
            'message': 'Stable Zero123测试完成'
        })

    except Exception as e:
        logger.error(f"Stable Zero123测试失败: {e}")
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

        logger.info(f"查询任务状态: task_id={task_id}")
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

                logger.info(f"任务完成: task_id={task_id}")
                # 回填历史记录（世界结果）
                try:
                    history_store.update_by_task_id(task_id, {
                        'status': 'completed',
                        'payload': {
                            'world_id': world_data.get('world_id', ''),
                            'world_url': world_data.get('world_marble_url', ''),
                            'preview_url': thumb or pano,
                            'pano_url': pano,
                            'thumbnail_url': thumb,
                            'caption': assets.get('caption', ''),
                        },
                    })
                except Exception as he:
                    logger.warning(f"回填历史失败: {he}")
                return jsonify({
                    'success': True,
                    'status': 'completed',
                    'result': {
                        'world_id': world_data.get('world_id', ''),
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
            logger.error(
                f"获取状态失败: {response.status_code} - {response.text[:200]}"
            )
            return jsonify({
                'success': False,
                'error': f'获取状态失败: {response.status_code}'
            }), response.status_code

    except Exception as e:
        logger.error(f"查询任务状态失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
