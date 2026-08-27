# -*- coding: utf-8 -*-
"""
Text-to-Image 生成器（支持 SD1.5 / SDXL）
基于 HuggingFace Diffusers 的 Stable Diffusion 文生图模块
支持运行时切换模型与分辨率/步数参数化
"""

import os
import time
import logging
import uuid
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List

# 延迟导入
_torch = None


def _get_torch():
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


logger = logging.getLogger(__name__)

# 预置的本地模型选项（可通过 TEXT_TO_IMAGE_MODEL 使用任意 HuggingFace ID 或本地路径）
MODEL_PRESETS = [
    {
        'id': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'label': 'Stable Diffusion v1.5（轻量，512px）',
        'pipeline': 'sd15',
        'default_size': 512,
    },
    {
        'id': 'stabilityai/sdxl-turbo',
        'label': 'SDXL Turbo（快速，512px）',
        'pipeline': 'sdxl',
        'default_size': 512,
    },
    {
        'id': 'stabilityai/stable-diffusion-xl-base-1.0',
        'label': 'SDXL Base 1.0（高质量，1024px，需大显存）',
        'pipeline': 'sdxl',
        'default_size': 1024,
    },
]


class TextToImageGenerator:
    """文生图生成器

    使用 Stable Diffusion / SDXL 将文本提示词转换为图片。
    生成的图片可用于 Stable Zero123 的 3D 生成流程。
    """

    def __init__(self, model_id: str = "stable-diffusion-v1-5/stable-diffusion-v1-5"):
        # 设置 HuggingFace 镜像（解决国内网络问题）
        if not os.environ.get('HF_ENDPOINT'):
            os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
        # 设置缓存目录到 D 盘（避免 C 盘空间不足）
        if not os.environ.get('HF_HOME'):
            os.environ['HF_HOME'] = 'D:\\hf_cache'
        # 禁用 xet 传输（某些网络环境下会卡住）
        os.environ['HF_HUB_DISABLE_XET'] = '1'

        self.model_id = os.environ.get(
            'TEXT_TO_IMAGE_MODEL', model_id
        )
        self.pipeline_type = self._detect_pipeline_type(self.model_id)
        self.pipe = None
        self.pipe_model = None  # 已加载管道对应的模型
        self.is_loaded = False
        self._model_lock = threading.Lock()

        # 默认参数（可被请求参数覆盖）
        self.default_params = {
            'width': int(os.environ.get('TEXT_TO_IMAGE_WIDTH', '512')),
            'height': int(os.environ.get('TEXT_TO_IMAGE_HEIGHT', '512')),
            'num_inference_steps': int(os.environ.get('TEXT_TO_IMAGE_STEPS', '20')),
            'guidance_scale': float(os.environ.get('TEXT_TO_IMAGE_GUIDANCE', '7.5')),
        }

        # 设备检测（委托统一工具模块）
        from utils.device import get_device, get_torch_dtype, is_torch_available
        self.device = get_device()
        self.torch_dtype = get_torch_dtype(self.device) if is_torch_available() else None

        # 输出目录（与 app.py 的 UPLOAD_DIR 一致：项目根目录/uploads/）
        default_output = os.path.join(
            os.path.dirname(__file__), '..', '..', 'uploads'
        )
        self.output_dir = Path(
            os.environ.get('TEXT_TO_IMAGE_OUTPUT_DIR', default_output)
        )
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"TextToImageGenerator 初始化完成，"
            f"模型: {self.model_id}（{self.pipeline_type}），设备: {self.device}"
        )

    def _detect_pipeline_type(self, model_id: str) -> str:
        """识别管线类型：sd15 / sdxl（可用 TEXT_TO_IMAGE_PIPELINE 强制指定）"""
        forced = os.environ.get('TEXT_TO_IMAGE_PIPELINE', 'auto').strip().lower()
        if forced in ('sd15', 'sdxl'):
            return forced
        name = (model_id or '').lower()
        if 'sdxl' in name or 'xl-base' in name or 'xl-turbo' in name:
            return 'sdxl'
        return 'sd15'

    def get_available_models(self) -> List[Dict[str, Any]]:
        """返回预置模型列表（供 /api/models 与前端下拉框使用）"""
        current = self.model_id
        models = []
        for preset in MODEL_PRESETS:
            models.append({
                'id': preset['id'],
                'label': preset['label'],
                'pipeline': preset['pipeline'],
                'default_size': preset['default_size'],
                'is_current': preset['id'] == current,
            })
        # 当前模型不在预置列表中时追加显示
        if current and current not in [m['id'] for m in MODEL_PRESETS]:
            models.insert(0, {
                'id': current,
                'label': f'{current}（自定义，{self.pipeline_type}）',
                'pipeline': self.pipeline_type,
                'default_size': 1024 if self.pipeline_type == 'sdxl' else 512,
                'is_current': True,
            })
        return models

    def get_default_params(self) -> Dict[str, Any]:
        return dict(self.default_params)

    def load_model(self, force_reload: bool = False) -> bool:
        """加载当前 model_id 对应的模型（线程安全）"""
        with self._model_lock:
            if self.is_loaded and not force_reload and self.pipe_model == self.model_id:
                return True

            try:
                _get_torch()
                pipeline_type = self._detect_pipeline_type(self.model_id)
                logger.info(
                    f"开始加载文生图模型: {self.model_id}（{pipeline_type}）"
                )

                if pipeline_type == 'sdxl':
                    from diffusers import StableDiffusionXLPipeline
                    self.pipe = StableDiffusionXLPipeline.from_pretrained(
                        self.model_id,
                        torch_dtype=self.torch_dtype,
                        low_cpu_mem_usage=True,
                        use_safetensors=True,
                        variant='fp16' if self.device == 'cuda' else None,
                    )
                else:
                    from diffusers import StableDiffusionPipeline
                    self.pipe = StableDiffusionPipeline.from_pretrained(
                        self.model_id,
                        torch_dtype=self.torch_dtype,
                        low_cpu_mem_usage=True,
                        safety_checker=None,  # 禁用安全检查以提升速度
                        use_safetensors=True,
                    )

                self.pipe = self.pipe.to(self.device)

                # CPU 优化
                if self.device == "cpu":
                    if hasattr(self.pipe, 'enable_attention_slicing'):
                        self.pipe.enable_attention_slicing()

                self.pipe_model = self.model_id
                self.pipeline_type = pipeline_type
                self.is_loaded = True
                logger.info("✅ 文生图模型加载成功")
                return True

            except Exception as e:
                logger.error(f"❌ 文生图模型加载失败: {e}")
                self.is_loaded = False
                self.pipe = None
                return False

    def _switch_model(self, model_id: str) -> bool:
        """切换模型（卸载旧管道并加载新模型）"""
        if model_id == self.pipe_model and self.is_loaded:
            return True
        logger.info(f"切换文生图模型: {self.pipe_model} -> {model_id}")
        self.model_id = model_id
        self.pipeline_type = self._detect_pipeline_type(model_id)
        self.is_loaded = False
        self.pipe = None
        return self.load_model(force_reload=True)

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: Optional[int] = None,
        height: Optional[int] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """从文本提示词生成图片

        Args:
            prompt: 文本提示词
            negative_prompt: 负面提示词（不想出现的内容）
            width/height: 图片宽高（None 使用默认值）
            num_inference_steps: 推理步数（None 使用默认值）
            guidance_scale: 指导尺度（None 使用默认值）
            model_id: 临时指定模型（None 使用当前模型）

        Returns:
            包含生成结果的字典
        """
        # 运行时切换模型
        if model_id and model_id != self.model_id:
            if not self._switch_model(model_id):
                return {
                    "success": False,
                    "error": f"模型加载失败: {model_id}"
                }

        if not self.is_loaded:
            if not self.load_model():
                return {
                    "success": False,
                    "error": "文生图模型加载失败，请确保已安装 torch 和 diffusers"
                }

        try:
            start_time = time.time()
            torch = _get_torch()

            # 参数覆盖（未指定时用默认值）
            width = width or self.default_params['width']
            height = height or self.default_params['height']
            steps = num_inference_steps or self.default_params['num_inference_steps']
            guidance = guidance_scale if guidance_scale is not None \
                else self.default_params['guidance_scale']

            # SDXL Turbo 系不支持 guidance_scale / 负面提示词
            is_turbo = 'turbo' in self.model_id.lower()

            logger.info(
                f"开始文生图，提示词: {prompt}，"
                f"{width}x{height}, steps={steps}, model={self.model_id}"
            )

            gen_kwargs = dict(
                prompt=prompt,
                width=width,
                height=height,
                num_inference_steps=steps,
                generator=torch.Generator(device=self.device).manual_seed(
                    int(time.time()) % 2 ** 32
                ),
            )
            if is_turbo:
                gen_kwargs['guidance_scale'] = 0.0
            else:
                gen_kwargs['guidance_scale'] = guidance
                if negative_prompt:
                    gen_kwargs['negative_prompt'] = negative_prompt

            result = self.pipe(**gen_kwargs)
            generated_image = result.images[0]

            # 保存图片
            filename = f"t2i_{uuid.uuid4().hex[:12]}.png"
            filepath = self.output_dir / filename
            generated_image.save(filepath, "PNG")

            image_url = f"/uploads/{filename}"
            generation_time = time.time() - start_time

            logger.info(
                f"文生图完成: {filename}，用时 {generation_time:.1f}s"
            )

            return {
                "success": True,
                "image_url": image_url,
                "filename": filename,
                "filepath": str(filepath),
                "generation_time": round(generation_time, 2),
                "prompt": prompt,
                "model": self.model_id,
                "pipeline": self.pipeline_type,
                "size": f"{width}x{height}",
                "steps": steps,
            }

        except Exception as e:
            logger.error(f"文生图失败: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def get_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        return {
            "model_name": "Stable Diffusion / SDXL",
            "model_id": self.model_id,
            "pipeline": self.pipeline_type,
            "is_loaded": self.is_loaded,
            "device": self.device,
            "supported_input": "文本提示词",
            "output_type": "PNG 图片",
            "capabilities": "text-to-image",
            "default_params": self.get_default_params(),
        }
