# -*- coding: utf-8 -*-
"""
统一的设备检测工具
供 smart_selector / stable_3d_generator / text_to_image 共用，避免三处重复检测
"""

import logging

logger = logging.getLogger(__name__)

_torch = None
_torch_checked = False


def _get_torch():
    """延迟导入 torch，结果缓存"""
    global _torch, _torch_checked
    if not _torch_checked:
        _torch_checked = True
        try:
            import torch
            _torch = torch
        except ImportError:
            logger.debug("torch 未安装")
    return _torch


def is_torch_available() -> bool:
    """torch 是否已安装"""
    return _get_torch() is not None


def get_device() -> str:
    """获取最佳可用设备：cuda | mps | cpu"""
    torch = _get_torch()
    if torch is None:
        return "cpu"
    try:
        if torch.cuda.is_available():
            gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if gpu_memory >= 4.0:
                return "cuda"
            logger.warning(f"GPU内存不足 ({gpu_memory:.1f}GB)，切换到CPU模式")
        if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
    except Exception as e:
        logger.warning(f"设备检测失败: {e}")
    return "cpu"


def get_gpu_memory_gb() -> float:
    """返回 GPU 显存（GB），无 CUDA 返回 0"""
    torch = _get_torch()
    if torch is None:
        return 0.0
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception as e:
        logger.debug(f"GPU 显存检测失败: {e}")
    return 0.0


def get_torch_dtype(device: str = None):
    """根据设备返回合适的 torch dtype（cuda → float16，其余 → float32）"""
    torch = _get_torch()
    if torch is None:
        return None
    dev = device or get_device()
    return torch.float16 if dev == "cuda" else torch.float32
