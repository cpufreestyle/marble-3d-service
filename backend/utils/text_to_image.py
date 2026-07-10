# -*- coding: utf-8 -*-
"""
Text-to-Image 生成器
基于 HuggingFace Diffusers 的 Stable Diffusion 文生图模块
将文本提示词转换为图片，供 Stable Zero123 进行 3D 生成
"""

import os
import time
import logging
import uuid
from pathlib import Path
from typing import Dict, Any

# 延迟导入
_torch = None
_diffusers_pipe = None


def _get_torch():
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger(__name__)


class TextToImageGenerator:
    """文生图生成器

    使用 Stable Diffusion 将文本提示词转换为图片。
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
        self.pipe = None
        self.is_loaded = False

        # 设备检测
        try:
            torch = _get_torch()
            if torch.cuda.is_available():
                self.device = "cuda"
                self.torch_dtype = torch.float16
            else:
                self.device = "cpu"
                self.torch_dtype = torch.float32
        except ImportError:
            logger.warning("torch 未安装，TextToImage 将不可用")
            self.device = "cpu"
            self.torch_dtype = None

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
            f"模型: {self.model_id}，设备: {self.device}"
        )

    def load_model(self) -> bool:
        """加载 Stable Diffusion 模型"""
        if self.is_loaded:
            return True

        try:
            _get_torch()
            from diffusers import StableDiffusionPipeline

            logger.info(f"开始加载文生图模型: {self.model_id}")

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

            self.is_loaded = True
            logger.info("✅ 文生图模型加载成功")
            return True

        except Exception as e:
            logger.error(f"❌ 文生图模型加载失败: {e}")
            self.is_loaded = False
            return False

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 512,
        height: int = 512,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.5
    ) -> Dict[str, Any]:
        """从文本提示词生成图片

        Args:
            prompt: 文本提示词
            negative_prompt: 负面提示词（不想出现的内容）
            width: 图片宽度
            height: 图片高度
            num_inference_steps: 推理步数
            guidance_scale: 指导尺度

        Returns:
            包含生成结果的字典
        """
        if not self.is_loaded:
            if not self.load_model():
                return {
                    "success": False,
                    "error": "文生图模型加载失败，请确保已安装 torch 和 diffusers"
                }

        try:
            start_time = time.time()
            torch = _get_torch()

            logger.info(f"开始文生图，提示词: {prompt}")

            # 生成图片
            result = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                width=width,
                height=height,
                num_inference_steps=num_inference_steps,
                guidance_scale=guidance_scale,
                generator=torch.Generator(device=self.device).manual_seed(
                    int(time.time()) % 2**32
                )
            )

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
                "model": "stable-diffusion-v1.5",
                "size": f"{width}x{height}"
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
            "model_name": "Stable Diffusion v1.5",
            "model_id": self.model_id,
            "is_loaded": self.is_loaded,
            "device": self.device,
            "supported_input": "文本提示词",
            "output_type": "PNG 图片",
            "capabilities": "text-to-image"
        }
