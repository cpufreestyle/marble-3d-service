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
from pathlib import Path
from datetime import datetime
import logging
from PIL import Image
import asyncio
import threading

# 导入智能选择器和Stable Zero123
from utils.smart_selector import SmartEngineSelector, GenerationEngine
from utils.stable_3d_generator import Stable3DGenerator

# 加载环境变量
load_dotenv()

world_bp = Blueprint('world', __name__)

# World Labs API 配置
API_KEY = os.environ.get('WORLD_LABS_API_KEY')
if not API_KEY:
    logging.warning("⚠️ 缺少 WORLD_LABS_API_KEY 环境变量。World Labs 引擎将不可用，请在 .env 文件中设置。")

API_URL = 'https://api.worldlabs.ai/marble/v1'

# 本地 LLM 配置
LM_STUDIO_URL = os.environ.get('LM_STUDIO_URL', 'http://localhost:1234/v1')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://localhost:11434')

# 上传目录
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

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
        thread = threading.Thread(target=lambda: asyncio_loop.run_forever(), daemon=True)
        thread.start()
    return asyncio_loop


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

        return jsonify({'success': False, 'error': '没有有效的图片文件'}), 400

    except Exception as e:
        logging.error(f"图片上传失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@world_bp.route('/uploads/<path:filename>')
def serve_upload(filename):
    """提供上传文件的访问"""
    return send_from_directory(UPLOAD_DIR, filename)


@world_bp.route('/create', methods=['POST'])
def create_world():
    """创建 3D 世界（支持智能引擎选择和图片上传）"""
    try:
        # ========== 1. 解析请求参数 ==========
        prompt = ''
        user_api_key = ''
        use_local_llm = True
        image_url = None
        image_file = None
        engine_preference = 'auto'

        if request.content_type and 'multipart/form-data' in request.content_type:
            prompt = request.form.get('prompt', '')
            user_api_key = request.form.get('api_key', '')
            use_local_llm = request.form.get('use_local_llm', 'true').lower() == 'true'
            engine_preference = request.form.get('engine', 'auto')
            image_file = request.files.get('image')

            if image_file and image_file.filename:
                ext = os.path.splitext(image_file.filename)[1].lower()
                if ext not in ['.jpg', '.jpeg', '.png', '.webp']:
                    return jsonify({'success': False, 'error': '只支持 JPG/PNG/WEBP 格式'}), 400

                filename = f"{uuid.uuid4().hex}{ext}"
                filepath = os.path.join(UPLOAD_DIR, filename)
                image_file.save(filepath)
                image_url = f"{request.host_url}uploads/{filename}"

        elif request.is_json:
            data = request.get_json()
            prompt = data.get('prompt', '')
            user_api_key = data.get('api_key', '')
            use_local_llm = data.get('use_local_llm', True)
            engine_preference = data.get('engine', 'auto')
            image_url = data.get('image_url')

        if not prompt and not image_url:
            return jsonify({'success': False, 'error': '请输入提示词或上传图片'}), 400

        # ========== 2. 本地 LLM 优化提示词（引擎选择前完成） ==========
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

        # ========== 3. 智能引擎选择 ==========
        has_image = bool(image_file or image_url)
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
            logging.info(f"智能引擎选择: {selected_engine.value} - {selection_result.reasoning}")

        except Exception as e:
            logging.warning(f"智能选择失败，使用默认引擎: {e}")
            selected_engine = GenerationEngine.WORLD_LABS

        # ========== 4. Stable Zero123 引擎处理 ==========
        if selected_engine == GenerationEngine.STABLE_3D and has_image:
            try:
                image_to_process = None
                if image_file:
                    # 从已保存的文件路径读取（避免stream已消费的问题）
                    saved_filepath = os.path.join(UPLOAD_DIR, filename)
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
                            'original_prompt': prompt,
                            'enhanced_prompt': final_prompt if final_prompt != prompt else None,
                            'llm_used': llm_used,
                            'image_url': image_url,
                            'message': '使用Stable Zero123生成了多视角3D视图'
                        })
                    else:
                        logging.warning(f"Stable Zero123失败，降级到World Labs: {stable_result.get('error')}")
                        selected_engine = GenerationEngine.WORLD_LABS

            except Exception as e:
                logging.error(f"Stable Zero123处理失败: {e}")
                selected_engine = GenerationEngine.WORLD_LABS

        # ========== 5. World Labs 引擎处理（默认/降级） ==========
        api_key = user_api_key if user_api_key else API_KEY

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


@world_bp.route('/engine-status')
def engine_status():
    """获取3D生成引擎状态"""
    try:
        # 获取智能选择器的状态报告
        status_report = smart_selector.get_engine_status_report()
        statistics = smart_selector.get_selection_statistics()

        # 获取Stable Zero123模型信息
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
            return jsonify({'success': False, 'error': '需要上传图片进行测试'}), 400

        image_file = request.files['image']
        prompt = request.form.get('prompt', 'a 3D model')

        # 打开图片
        image = Image.open(image_file.stream).convert('RGB')

        # 启动异步任务
        loop = get_asyncio_loop()
        result = loop.run_coroutine_threadsafe(
            stable_3d_generator.generate_3d_from_image(image, prompt, num_views=2),  # 快速测试用2个视图
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
