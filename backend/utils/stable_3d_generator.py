# -*- coding: utf-8 -*-
"""
Stable Zero123 系列 3D 生成器（多后端）
支持三种本地图片到 3D 多视角后端，按 STABLE_3D_BACKEND 配置或自动选择：
  - zero123plus   : Zero123++（sudo-ai/zero123plus-v1.2），一次生成 6 视角，需 GPU
  - stable-zero123: Stable Zero123（ds8nh/Stable-Zero123），按方位角逐视角，需 GPU
  - sd-img2img    : Stable Diffusion img2img（CPU 可用，兼容旧版行为）
"""

import os
import asyncio
import logging
import time
import threading
from typing import Dict, Any, Optional, List
from pathlib import Path
from io import BytesIO

# PIL 是必需依赖（在 requirements.txt 中）
from PIL import Image

# torch 和 numpy 是可选依赖（在 requirements-open-source.txt 中）
# 延迟导入，避免未安装时整个应用无法启动
_torch = None
_np = None


def _get_torch():
    """延迟导入 torch"""
    global _torch
    if _torch is None:
        try:
            import torch
            _torch = torch
        except ImportError:
            raise ImportError(
                "torch 未安装。请运行: pip install -r requirements-open-source.txt"
            )
    return _torch


def _get_numpy():
    """延迟导入 numpy"""
    global _np
    if _np is None:
        try:
            import numpy
            _np = numpy
        except ImportError:
            raise ImportError(
                "numpy 未安装。请运行: pip install -r requirements-open-source.txt"
            )
    return _np


logger = logging.getLogger(__name__)

# 后端规格定义：auto 模式按列表顺序（优先级）尝试
BACKEND_SPECS = {
    'zero123plus': {
        'default_model': 'sudo-ai/zero123plus-v1.2',
        'model_env': 'STABLE_3D_ZERO123PLUS_MODEL',
        'min_gpu_gb': 6.0,   # fp16 约需 6-8GB 显存
        'fixed_views': 6,    # 单次生成固定 6 视角（3x2 网格）
    },
    'stable-zero123': {
        'default_model': 'ds8nh/Stable-Zero123',
        'model_env': 'STABLE_3D_ZERO123_MODEL',
        'min_gpu_gb': 6.0,
        'fixed_views': None,  # 按方位角逐个生成
    },
    'sd-img2img': {
        'default_model': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'model_env': 'STABLE_3D_MODEL_PATH',
        'min_gpu_gb': 0.0,    # CPU 可用
        'fixed_views': None,
    },
}

AUTO_BACKEND_PRIORITY = ['zero123plus', 'stable-zero123', 'sd-img2img']


class Stable3DGenerator:
    """Stable Zero123 系多后端 3D 生成器"""

    def __init__(self, backend: str = None):
        # HuggingFace 端点：默认直连 huggingface.co，可通过 HF_ENDPOINT 切换镜像
        if not os.environ.get('HF_ENDPOINT'):
            os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
        # 设置缓存目录到 D 盘（避免 C 盘空间不足）
        if not os.environ.get('HF_HOME'):
            os.environ['HF_HOME'] = 'D:\\hf_cache'
        # 禁用 xet 传输
        os.environ['HF_HUB_DISABLE_XET'] = '1'

        self.configured_backend = (
            backend or os.environ.get('STABLE_3D_BACKEND', 'auto')
        ).strip().lower() or 'auto'
        if self.configured_backend not in list(BACKEND_SPECS) + ['auto']:
            logger.warning(
                f"未知 STABLE_3D_BACKEND={self.configured_backend}，回退到 auto"
            )
            self.configured_backend = 'auto'

        self.pipe = None
        self.pipe_backend = None  # 当前已加载管道对应的后端
        self.pipe_model = None    # 当前已加载管道对应的模型
        self.is_loaded = False
        self.effective_backend = None  # 实际生效的后端（加载时解析）
        self._model_lock = threading.Lock()

        # 尝试检测设备
        try:
            self.device = self._get_device()
        except Exception as e:
            logger.warning(f"设备检测失败，使用CPU: {e}")
            self.device = "cpu"

        self.default_num_views = int(os.environ.get('STABLE_3D_NUM_VIEWS', '4'))

        # 生成的图像保存目录（默认为 backend/generated_3d_views/）
        default_output = os.path.join(os.path.dirname(__file__), '..', 'generated_3d_views')
        self.output_dir = Path(os.environ.get('STABLE_3D_OUTPUT_DIR', default_output))
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"Stable3DGenerator 初始化完成，设备: {self.device}，"
            f"配置后端: {self.configured_backend}"
        )
        logger.info(f"输出目录: {self.output_dir}")

    # ===== 设备与后端可用性 =====
    def _get_device(self) -> str:
        """获取最佳可用设备（委托统一工具模块）"""
        from utils.device import get_device
        return get_device()

    def _gpu_memory_gb(self) -> float:
        """返回 GPU 显存（GB），无 CUDA 返回 0"""
        from utils.device import get_gpu_memory_gb
        return get_gpu_memory_gb()

    def _diffusers_available(self) -> bool:
        try:
            import diffusers  # noqa: F401
            return True
        except ImportError:
            return False

    def get_backend_availability(self) -> List[Dict[str, Any]]:
        """返回各后端的可用性与原因（不做模型下载，仅静态检查）"""
        gpu_gb = self._gpu_memory_gb()
        diffusers_ok = self._diffusers_available()
        availability = []
        for name in AUTO_BACKEND_PRIORITY:
            spec = BACKEND_SPECS[name]
            available, reason = True, None
            if not diffusers_ok:
                available, reason = False, 'diffusers 未安装'
            elif spec['min_gpu_gb'] > 0 and self.device == 'cpu':
                available, reason = False, '需要 CUDA GPU'
            elif spec['min_gpu_gb'] > 0 and gpu_gb < spec['min_gpu_gb']:
                available, reason = (
                    False,
                    f'显存不足: {gpu_gb:.1f}GB < {spec["min_gpu_gb"]}GB',
                )
            availability.append({
                'name': name,
                'model': self._backend_model(name),
                'available': available,
                'reason': reason,
                'requires_gpu': spec['min_gpu_gb'] > 0,
            })
        return availability

    def _resolve_backend(self, requested: Optional[str]) -> str:
        """解析实际使用的后端：显式指定直接用；auto 按优先级取第一个可用"""
        requested = (requested or self.configured_backend).strip().lower()
        if requested != 'auto':
            if requested not in BACKEND_SPECS:
                raise ValueError(f"未知 3D 后端: {requested}")
            return requested

        for item in self.get_backend_availability():
            if item['available']:
                return item['name']
        # 理论上 sd-img2img 始终兜底（CPU 可用）；若 diffusers 缺失则无可选
        raise ImportError("无可用 3D 后端，请安装 requirements-open-source.txt")

    @staticmethod
    def _backend_model(backend: str) -> str:
        spec = BACKEND_SPECS[backend]
        return os.environ.get(spec['model_env'], spec['default_model'])

    # ===== 模型加载 =====
    def load_model(self, force_reload: bool = False, backend: str = None) -> bool:
        """加载指定后端的模型（线程安全）"""
        with self._model_lock:
            target = self._resolve_backend(backend)
            model_id = self._backend_model(target)

            if (self.is_loaded and not force_reload
                    and self.pipe_backend == target
                    and self.pipe_model == model_id):
                return True

            try:
                if target == 'zero123plus':
                    self._load_zero123plus(model_id)
                elif target == 'stable-zero123':
                    self._load_stable_zero123(model_id)
                else:
                    self._load_sd_img2img(model_id)

                self.pipe_backend = target
                self.pipe_model = model_id
                self.effective_backend = target
                self.is_loaded = True
                logger.info(f"✅ 3D 模型加载成功 [{target}]: {model_id}，设备: {self.device}")
                return True
            except Exception as e:
                logger.error(f"❌ 模型加载失败 [{target}]: {e}")
                self.is_loaded = False
                self.pipe = None
                return False

    def _load_zero123plus(self, model_id: str):
        """加载 Zero123++（一次生成 6 视角网格）"""
        torch = _get_torch()
        from diffusers import DiffusionPipeline

        logger.info(f"开始加载 Zero123++: {model_id}")
        dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.pipe = DiffusionPipeline.from_pretrained(
            model_id,
            custom_pipeline='sudo-ai/zero123plus-v1.2',
            torch_dtype=dtype,
        )
        self.pipe = self.pipe.to(self.device)
        self._apply_common_optimizations()

    def _load_stable_zero123(self, model_id: str):
        """加载 Stable Zero123（按方位角逐视角）"""
        torch = _get_torch()
        from diffusers import Zero123Pipeline

        logger.info(f"开始加载 Stable Zero123: {model_id}")
        dtype = torch.float16 if self.device == 'cuda' else torch.float32
        self.pipe = Zero123Pipeline.from_pretrained(model_id, torch_dtype=dtype)
        self.pipe = self.pipe.to(self.device)
        self._apply_common_optimizations()

    def _load_sd_img2img(self, model_id: str):
        """加载 Stable Diffusion img2img（兜底后端，CPU 可用）"""
        torch = _get_torch()
        from diffusers import (
            StableDiffusionImg2ImgPipeline,
            EulerAncestralDiscreteScheduler,
        )

        logger.info(f"开始加载 SD img2img: {model_id}")
        self.pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
            model_id,
            torch_dtype=torch.float16 if self.device == 'cuda' else torch.float32,
            use_safetensors=True,
            low_cpu_mem_usage=True,
            safety_checker=None,
        )
        self.pipe.scheduler = EulerAncestralDiscreteScheduler.from_config(
            self.pipe.scheduler.config
        )
        self.pipe = self.pipe.to(self.device)
        self._apply_common_optimizations()

    def _apply_common_optimizations(self):
        """通用推理优化（GPU: xformers；CPU: attention slicing）"""
        if self.device == 'cuda':
            try:
                self.pipe.enable_xformers_memory_efficient_attention()
                logger.info("已启用xformers内存优化")
            except Exception as e:
                logger.warning(f"启用xformers失败: {e}")
        if hasattr(self.pipe, 'enable_attention_slicing'):
            self.pipe.enable_attention_slicing()

    # ===== 预处理 =====
    async def _preprocess_image(self, image: Image.Image, target_size: int = 512) -> Image.Image:
        """预处理输入图片：RGB 化 + 缩放（Zero123++ 需 336，其余 512）"""
        if image.mode != 'RGB':
            image = image.convert('RGB')

        if max(image.size) != target_size:
            ratio = target_size / max(image.size)
            new_size = (int(image.size[0] * ratio), int(image.size[1] * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)

            if min(new_size) < target_size:
                new_image = Image.new('RGB', (target_size, target_size), (0, 0, 0))
                paste_x = (target_size - new_size[0]) // 2
                paste_y = (target_size - new_size[1]) // 2
                new_image.paste(image, (paste_x, paste_y))
                image = new_image

        return image

    # ===== 生成 =====
    async def generate_3d_from_image(self,
                                     image: Image.Image,
                                     prompt: str = "a 3D model",
                                     num_views: int = 4,
                                     guidance_scale: float = 3.0,
                                     num_inference_steps: int = 25,
                                     backend: str = None) -> Dict[str, Any]:
        """从图片生成多视角 3D

        Args:
            image: 输入图片
            prompt: 生成提示词
            num_views: 生成视角数量（zero123plus 固定 6，忽略此参数）
            guidance_scale: 指导尺度
            num_inference_steps: 推理步数
            backend: 指定后端（None 使用服务端配置）

        Returns:
            包含生成结果的字典
        """
        try:
            target_backend = self._resolve_backend(backend)
        except (ValueError, ImportError) as e:
            return {
                "success": False,
                "error": str(e),
                "model": "stable-zero123-series",
            }

        # 按需加载 / 切换后端
        need_reload = (
            not self.is_loaded
            or self.pipe_backend != target_backend
            or self.pipe_model != self._backend_model(target_backend)
        )
        if need_reload:
            loop = asyncio.get_running_loop()
            if not await loop.run_in_executor(
                None, lambda: self.load_model(backend=target_backend)
            ):
                return {
                    "success": False,
                    "error": f"模型加载失败（后端 {target_backend}）",
                    "model": "stable-zero123-series",
                }

        try:
            if target_backend == 'zero123plus':
                return await self._generate_via_zero123plus(
                    image, prompt, num_inference_steps
                )
            if target_backend == 'stable-zero123':
                return await self._generate_via_stable_zero123(
                    image, prompt, num_views, num_inference_steps
                )
            return await self._generate_via_sd_img2img(
                image, prompt, num_views, guidance_scale, num_inference_steps
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(f"3D 生成失败 [{target_backend}]: {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "model": "stable-zero123-series",
                "error_details": "3D生成过程中发生错误，请检查输入图片格式和大小",
            }

    def _save_view(self, generated_image: Image.Image, timestamp: int, index: int) -> str:
        """保存单个视角图片，返回相对 URL"""
        filename = f"view_{timestamp}_{index}.png"
        generated_image.save(self.output_dir / filename, "PNG")
        return f"generated_3d_views/{filename}"

    async def _generate_via_zero123plus(self,
                                        image: Image.Image,
                                        prompt: str,
                                        num_inference_steps: int) -> Dict[str, Any]:
        """Zero123++：一次生成 6 视角（3x2 网格）并切分"""
        start_time = time.time()
        timestamp = int(start_time)
        num_views = BACKEND_SPECS['zero123plus']['fixed_views']

        logger.info(f"Zero123++ 开始生成 {num_views} 视角")
        processed = await self._preprocess_image(image, target_size=336)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.pipe(
                prompt=" ",
                image=processed,
                num_inference_steps=num_inference_steps,
                guidance_scale=1.0,
            )
        )
        grid_image = result.images[0]

        # 切分 3x2 网格为单个视角
        w, h = grid_image.size
        tile_w, tile_h = w // 3, h // 2
        view_urls, metadata = [], []
        for i in range(num_views):
            row, col = divmod(i, 3)
            tile = grid_image.crop((
                col * tile_w, row * tile_h,
                (col + 1) * tile_w, (row + 1) * tile_h,
            ))
            url = self._save_view(tile, timestamp, i)
            view_urls.append(url)
            metadata.append({
                "view_index": i,
                "url": url,
                "seed": timestamp + i,
            })

        total_time = time.time() - start_time
        logger.info(f"Zero123++ 生成完成: {num_views} 视角，用时 {total_time:.2f}秒")
        return self._build_result(
            prompt, view_urls, metadata, total_time, 'zero123++', num_views
        )

    async def _generate_via_stable_zero123(self,
                                           image: Image.Image,
                                           prompt: str,
                                           num_views: int,
                                           num_inference_steps: int) -> Dict[str, Any]:
        """Stable Zero123：按方位角逐视角生成"""
        start_time = time.time()
        timestamp = int(start_time)
        num_views = max(1, min(num_views or self.default_num_views, 8))

        logger.info(f"Stable Zero123 开始生成 {num_views} 视角")
        processed = await self._preprocess_image(image, target_size=512)

        # (方位角, 仰角) 序列，单位：度
        angle_step = 360 / num_views
        view_urls, metadata = [], []

        for i in range(num_views):
            azimuth = i * angle_step
            view_start = time.time()
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda az=azimuth: self.pipe(
                        image=processed,
                        prompt="",
                        elevation=0.0,
                        azimuth=az,
                        base_elevation=0.0,
                        base_azimuth=0.0,
                        num_inference_steps=num_inference_steps,
                    )
                )
                url = self._save_view(result.images[0], timestamp, i)
                view_urls.append(url)
                metadata.append({
                    "view_index": i,
                    "url": url,
                    "azimuth": azimuth,
                    "generation_time": time.time() - view_start,
                })
                logger.info(f"视角 {i + 1}/{num_views} (azimuth={azimuth:.0f}°) 完成")
            except Exception as view_error:
                logger.error(f"视角 {i + 1} 生成失败: {view_error}")
                continue  # 不中断其余视角

        if not view_urls:
            return {
                "success": False,
                "error": "所有视角生成失败",
                "model": "stable-zero123",
            }

        total_time = time.time() - start_time
        return self._build_result(
            prompt, view_urls, metadata, total_time, 'stable-zero123', len(view_urls)
        )

    async def _generate_via_sd_img2img(self,
                                       image: Image.Image,
                                       prompt: str,
                                       num_views: int,
                                       guidance_scale: float,
                                       num_inference_steps: int) -> Dict[str, Any]:
        """SD img2img：多视角提示词逐张生成（兜底后端，兼容旧行为）"""
        start_time = time.time()
        timestamp = int(start_time)
        num_views = max(1, min(num_views or self.default_num_views, 8))

        logger.info(f"SD img2img 开始生成 {num_views} 视角")
        processed = await self._preprocess_image(image, target_size=512)

        view_prompts = [
            f"{prompt}, front view, centered, studio lighting",
            f"{prompt}, side view, left angle, studio lighting",
            f"{prompt}, back view, studio lighting",
            f"{prompt}, top-down view, overhead angle",
            f"{prompt}, side view, right angle, studio lighting",
            f"{prompt}, three-quarter view, studio lighting",
            f"{prompt}, close-up detail view",
            f"{prompt}, wide angle perspective view",
        ]

        view_urls, metadata = [], []
        for i in range(num_views):
            current_prompt = (
                view_prompts[i] if i < len(view_prompts) else f"{prompt}, view {i + 1}"
            )
            view_start = time.time()
            try:
                torch = _get_torch()
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda p=current_prompt, seed=timestamp + i: self.pipe(
                        prompt=p,
                        image=processed,
                        num_inference_steps=num_inference_steps,
                        guidance_scale=guidance_scale,
                        strength=0.6,
                        output_type="pil",
                        generator=torch.Generator(device=self.device).manual_seed(seed),
                    )
                )
                url = self._save_view(result.images[0], timestamp, i)
                view_urls.append(url)
                metadata.append({
                    "view_index": i,
                    "url": url,
                    "generation_time": time.time() - view_start,
                    "seed": timestamp + i,
                })
                logger.info(f"视角 {i + 1}/{num_views} 完成: {url}")
            except Exception as view_error:
                logger.error(f"视角 {i + 1} 生成失败: {view_error}")
                continue

        if not view_urls:
            return {
                "success": False,
                "error": "所有视角生成失败",
                "model": "sd-img2img",
            }

        total_time = time.time() - start_time
        return self._build_result(
            prompt, view_urls, metadata, total_time, 'sd-img2img', len(view_urls)
        )

    def _build_result(self, prompt, view_urls, metadata, total_time, backend, view_count):
        return {
            "success": True,
            "type": "multi_view_3d_stable_zero123",
            "original_prompt": prompt,
            "backend": backend,
            "generated_views": metadata,
            "view_count": view_count,
            "view_urls": view_urls,
            "generation_time": total_time,
            "model_used": backend,
            "device": self.device,
            "message": f"成功生成 {view_count} 个3D视角（后端: {backend}）",
            "usage_instructions": {
                "threejs_example": "使用Three.js的ImageLoader加载多视角图片，创建全景或3D展示",
                "file_format": "PNG格式的多视角图像",
                "recommended_viewer": "支持多视角3D展示的WebGL框架",
            },
        }

    async def generate_3d_from_data(self, image_data: bytes, prompt: str = "a 3D model", **kwargs) -> Dict[str, Any]:
        """从字节数据生成3D（适用于上传的图片）"""
        try:
            image = Image.open(BytesIO(image_data))
            return await self.generate_3d_from_image(image, prompt, **kwargs)
        except Exception as e:
            logger.error(f"图片数据解析失败: {e}")
            return {
                "success": False,
                "error": f"图片解析失败: {e}",
                "model": "stable-zero123-series",
            }

    def get_model_info(self) -> Dict[str, Any]:
        """获取模型信息"""
        availability = self.get_backend_availability()
        return {
            "model_name": "Stable Zero123 系列",
            "configured_backend": self.configured_backend,
            "effective_backend": self.effective_backend,
            "available_backends": availability,
            "is_loaded": self.is_loaded,
            "device": self.device,
            "gpu_memory_gb": round(self._gpu_memory_gb(), 1),
            "output_dir": str(self.output_dir),
            "supported_input": "单个图片 (JPG/PNG/WEBP)",
            "output_type": "多视角3D图像",
            "requirements": "zero123plus/stable-zero123 需 6GB+ 显存 GPU；sd-img2img 支持 CPU",
        }

    async def cleanup_old_files(self, max_age_hours: int = 24):
        """清理旧的生成文件

        Args:
            max_age_hours: 文件最大保留时间（小时）
        """
        try:
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600

            deleted_count = 0
            for file_path in self.output_dir.glob("*.png"):
                if current_time - file_path.stat().st_mtime > max_age_seconds:
                    file_path.unlink()
                    deleted_count += 1

            logger.info(f"清理完成: 删除 {deleted_count} 个过期文件")

        except Exception as e:
            logger.error(f"文件清理失败: {e}")
