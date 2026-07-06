# -*- coding: utf-8 -*-
"""
智能3D生成引擎选择器
根据输入类型、资源可用性和性能要求自动选择最佳生成引擎
"""

import os
import asyncio
import time
import logging
import threading
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

try:
    import psutil
except ImportError:
    psutil = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)
logger = logging.getLogger(__name__)


class GenerationEngine(Enum):
    """可选择的生成引擎"""
    WORLD_LABS = "world_labs"
    STABLE_3D = "stable_3d"
    HYBRID = "hybrid"
    AUTO = "auto"


class PromptComplexity(Enum):
    """提示词复杂度分类"""
    SIMPLE = "simple"     # 简单描述，少于10个词
    MODERATE = "moderate"  # 中等描述，10-30个词
    COMPLEX = "complex"   # 复杂描述，超过30个词或有细节要求


@dataclass
class EngineStatus:
    """引擎状态信息"""
    name: str
    available: bool
    last_check_time: float
    average_response_time: float = 0.0
    success_rate: float = 0.0
    quality_score: float = 0.0
    error_message: Optional[str] = None
    resource_usage: Dict[str, float] = field(default_factory=dict)


@dataclass
class GenerationRequest:
    """生成请求信息"""
    prompt: str
    has_image: bool
    complexity: PromptComplexity
    user_preference: Optional[str] = None
    urgency_level: int = 1  # 1-5，5为最高紧急度


@dataclass
class SelectionResult:
    """选择结果"""
    selected_engine: GenerationEngine
    confidence_score: float
    reasoning: str
    estimated_time: float
    fallback_plan: Optional[GenerationEngine] = None


class SmartEngineSelector:
    """智能3D生成引擎选择器

    根据多种因素自动选择最佳的3D生成引擎，包括：
    - 输入类型（纯文本 vs 图片+文本）
    - 提示词复杂度
    - 资源可用性
    - 用户偏好
    - 性能要求
    """

    def __init__(self):
        self.engine_status = {
            GenerationEngine.WORLD_LABS: EngineStatus("World Labs", True, time.time()),
            GenerationEngine.STABLE_3D: EngineStatus("Stable Zero123", True, time.time())
        }

        self.selection_history = []
        self.max_history_size = 100

        # 性能权重配置
        self.weights = {
            "quality": 0.4,
            "speed": 0.2,
            "availability": 0.3,
            "resource_efficiency": 0.1
        }

        # 引擎特性评分（0-1）
        self.engine_capabilities = {
            GenerationEngine.WORLD_LABS: {
                "text_to_3d": 0.95,
                "image_to_3d": 0.9,
                "quality": 0.95,
                "speed": 0.7,
                "resource_efficiency": 1.0  # 云端API，不占用本地资源
            },
            GenerationEngine.STABLE_3D: {
                "text_to_3d": 0.3,  # 主要支持图片到3D
                "image_to_3d": 0.8,
                "quality": 0.7,
                "speed": 0.4,  # 本地生成较慢
                "resource_efficiency": 0.2  # 资源消耗大
            }
        }

        # 定期更新引擎状态
        self._status_update_task = None
        self._start_periodic_status_check()

        logger.info("SmartEngineSelector 初始化完成")

    def _determine_prompt_complexity(self, prompt: str) -> PromptComplexity:
        """分析提示词复杂度"""
        word_count = len(prompt.split())
        detail_keywords = ['detailed', 'realistic', 'complex', 'specific', 'particular',
                           '详细的', '复杂的', '具体的', '特定的', '高质量']

        detail_count = sum(1 for keyword in detail_keywords if keyword in prompt.lower())

        if word_count > 30 or detail_count >= 2:
            return PromptComplexity.COMPLEX
        elif word_count > 10 or detail_count >= 1:
            return PromptComplexity.MODERATE
        else:
            return PromptComplexity.SIMPLE

    def _check_worldlabs_availability(self) -> Tuple[bool, Optional[str]]:
        """检查World Labs可用性"""
        try:
            # 检查环境变量
            api_key = os.environ.get('WORLD_LABS_API_KEY')
            if not api_key:
                return False, "缺少 WORLD_LABS_API_KEY 环境变量"

            # 可以添加简单的连通性测试
            # 为了简单起见，这里默认返回可用
            return True, None

        except Exception as e:
            return False, f"World Labs检查失败: {e}"

    def _check_stable3d_availability(self) -> Tuple[bool, Optional[str]]:
        """检查Stable Zero123可用性"""
        try:
            # 检查GPU和内存要求
            import torch

            if torch.cuda.is_available():
                # 检查GPU内存
                gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)
                if gpu_memory < 4.0:
                    return False, f"GPU内存不足: {gpu_memory:.1f}GB < 4.0GB"
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                # Apple Silicon
                pass  # 假设可用
            else:
                # CPU模式，检查系统内存（简化检查）
                if psutil:
                    system_memory = psutil.virtual_memory().available / (1024**3)
                    if system_memory < 8.0:
                        return False, f"系统内存不足: {system_memory:.1f}GB < 8.0GB"
                else:
                    # 如果没有psutil，使用默认假设
                    pass

            return True, None

        except ImportError:
            return False, "PyTorch或其他依赖未安装"
        except Exception as e:
            return False, f"Stable Zero123检查失败: {e}"

    async def _update_engine_status(self):
        """执行一次引擎状态更新（由 _start_periodic_status_check 定期调用）"""
        try:
            # 更新World Labs状态
            available, error = self._check_worldlabs_availability()
            self.engine_status[GenerationEngine.WORLD_LABS].available = available
            self.engine_status[GenerationEngine.WORLD_LABS].last_check_time = time.time()
            if error:
                self.engine_status[GenerationEngine.WORLD_LABS].error_message = error

            # 更新Stable Zero123状态
            available, error = self._check_stable3d_availability()
            self.engine_status[GenerationEngine.STABLE_3D].available = available
            self.engine_status[GenerationEngine.STABLE_3D].last_check_time = time.time()
            if error:
                self.engine_status[GenerationEngine.STABLE_3D].error_message = error

            logger.info(f"引擎状态更新: World Labs={self.engine_status[GenerationEngine.WORLD_LABS].available}, "
                        f"Stable Zero123={self.engine_status[GenerationEngine.STABLE_3D].available}")

        except Exception as e:
            logger.error(f"引擎状态更新失败: {e}")

    def _start_periodic_status_check(self):
        """启动定期状态检查"""
        async def status_check_loop():
            while True:
                try:
                    await asyncio.sleep(300)  # 每5分钟检查一次
                    await self._update_engine_status()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"状态检查循环错误: {e}")

        # 在单独的线程中运行状态检查
        def run_status_check():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(status_check_loop())

        thread = threading.Thread(target=run_status_check, daemon=True)
        thread.start()

    def _calculate_engine_score(self,
                                engine: GenerationEngine,
                                request: GenerationRequest) -> float:
        """计算引擎适合度分数"""
        capabilities = self.engine_capabilities.get(engine, {})
        status = self.engine_status.get(engine)

        if not status or not status.available:
            return 0.0

        # 基于输入类型的评分
        if request.has_image:
            input_score = capabilities.get("image_to_3d", 0.0)
        else:
            input_score = capabilities.get("text_to_3d", 0.0)

        # 基于复杂度的评分调整
        if request.complexity == PromptComplexity.COMPLEX:
            # 复杂任务偏向质量更好的引擎
            complexity_multiplier = capabilities.get("quality", 0.5)
        elif request.complexity == PromptComplexity.SIMPLE:
            # 简单任务可以考虑速度
            complexity_multiplier = capabilities.get("speed", 0.5)
        else:
            complexity_multiplier = 0.75

        # 资源效率评分
        resource_score = capabilities.get("resource_efficiency", 0.5)

        # 综合评分
        total_score = (
            input_score * self.weights["quality"] +
            complexity_multiplier * self.weights["quality"] +
            status.average_response_time * self.weights["speed"] +
            resource_score * self.weights["resource_efficiency"] +
            float(status.available) * self.weights["availability"]
        )

        return total_score

    async def select_best_engine(self,
                                 prompt: str,
                                 has_image: bool = False,
                                 user_preference: Optional[str] = None,
                                 urgency_level: int = 1) -> SelectionResult:
        """选择最佳生成引擎

        Args:
            prompt: 提示词
            has_image: 是否有图片
            user_preference: 用户偏好（world_labs, stable_3d, auto）
            urgency_level: 紧急度（1-5）

        Returns:
            选择结果
        """
        try:
            # 创建请求对象
            request = GenerationRequest(
                prompt=prompt,
                has_image=has_image,
                complexity=self._determine_prompt_complexity(prompt),
                user_preference=user_preference,
                urgency_level=urgency_level
            )

            # 处理用户偏好
            if user_preference and user_preference != "auto":
                try:
                    preferred_engine = GenerationEngine(user_preference)
                    if self.engine_status.get(preferred_engine, EngineStatus("", False, 0)).available:
                        return SelectionResult(
                            selected_engine=preferred_engine,
                            confidence_score=0.8,
                            reasoning=f"使用用户偏好: {preferred_engine.value}",
                            estimated_time=self._estimate_generation_time(preferred_engine, request)
                        )
                except ValueError:
                    pass  # 无效的用户偏好，继续使用自动选择

            # 自动选择逻辑
            engine_scores = {}
            for engine in [GenerationEngine.WORLD_LABS, GenerationEngine.STABLE_3D]:
                if self.engine_status[engine].available:
                    score = self._calculate_engine_score(engine, request)
                    engine_scores[engine] = score

            if not engine_scores:
                # 没有可用引擎，返回降级方案
                return SelectionResult(
                    selected_engine=GenerationEngine.WORLD_LABS,  # 作为最后的尝试
                    confidence_score=0.1,
                    reasoning="无可用引擎，尝试World Labs",
                    estimated_time=30.0,
                    fallback_plan=None
                )

            # 选择得分最高的引擎
            best_engine = max(engine_scores.keys(), key=lambda k: engine_scores[k])
            confidence = engine_scores[best_engine]

            # 选择备用引擎
            fallback_engine = None
            if len(engine_scores) > 1:
                fallback_engine = max((e for e in engine_scores.keys() if e != best_engine),
                                      key=lambda k: engine_scores[k], default=None)

            # 生成选择理由
            reasoning = self._generate_selection_reasoning(best_engine, engine_scores, request)

            result = SelectionResult(
                selected_engine=best_engine,
                confidence_score=confidence,
                reasoning=reasoning,
                estimated_time=self._estimate_generation_time(best_engine, request),
                fallback_plan=fallback_engine
            )

            # 记录选择历史
            self._record_selection(result, request)

            logger.info(f"引擎选择: {best_engine.value} (分数: {confidence:.3f})")
            return result

        except Exception as e:
            logger.error(f"引擎选择失败: {e}")
            # 降级到World Labs
            return SelectionResult(
                selected_engine=GenerationEngine.WORLD_LABS,
                confidence_score=0.1,
                reasoning=f"选择过程出错，使用默认引擎: {e}",
                estimated_time=30.0
            )

    def _estimate_generation_time(self, engine: GenerationEngine, request: GenerationRequest) -> float:
        """估计生成时间"""
        base_times = {
            GenerationEngine.WORLD_LABS: 15.0,
            GenerationEngine.STABLE_3D: 25.0
        }

        base_time = base_times.get(engine, 30.0)

        # 根据复杂度调整
        if request.complexity == PromptComplexity.COMPLEX:
            base_time *= 1.5
        elif request.complexity == PromptComplexity.MODERATE:
            base_time *= 1.2

        # 根据是否包含图片调整
        if request.has_image:
            if engine == GenerationEngine.STABLE_3D:
                base_time *= 0.8  # Stable Zero123对图片更友好
            else:
                base_time *= 1.1

        return max(base_time, 5.0)  # 至少5秒

    def _generate_selection_reasoning(self,
                                      best_engine: GenerationEngine,
                                      scores: Dict[GenerationEngine, float],
                                      request: GenerationRequest) -> str:
        """生成选择理由"""
        reasons = []

        if request.has_image:
            reasons.append("输入包含图片")

        if request.complexity == PromptComplexity.COMPLEX:
            reasons.append("复杂生成任务")
        elif request.complexity == PromptComplexity.SIMPLE:
            reasons.append("简单生成任务")

        engine_name = best_engine.value.replace("_", " ").title()

        if best_engine == GenerationEngine.WORLD_LABS:
            reasons.append("World Labs在质量和可靠性方面表现更好")
        elif best_engine == GenerationEngine.STABLE_3D:
            if request.has_image:
                reasons.append("Stable Zero123专为图片到3D优化")
            reasons.append("选择开源本地解决方案")

        return f"{engine_name}: " + "，".join(reasons)

    def _record_selection(self, result: SelectionResult, request: GenerationRequest):
        """记录选择历史"""
        self.selection_history.append({
            'timestamp': time.time(),
            'engine': result.selected_engine.value,
            'prompt_complexity': request.complexity.value,
            'has_image': request.has_image,
            'confidence': result.confidence_score
        })

        # 保持历史记录大小
        if len(self.selection_history) > self.max_history_size:
            self.selection_history = self.selection_history[-self.max_history_size:]

    def get_selection_statistics(self) -> Dict[str, Any]:
        """获取选择统计信息"""
        if not self.selection_history:
            return {"message": "暂无选择历史"}

        engine_counts = {}
        for record in self.selection_history:
            engine = record['engine']
            engine_counts[engine] = engine_counts.get(engine, 0) + 1

        avg_confidence = sum(r['confidence'] for r in self.selection_history) / len(self.selection_history)

        return {
            'total_selections': len(self.selection_history),
            'engine_distribution': engine_counts,
            'average_confidence': avg_confidence,
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        }

    def get_engine_status_report(self) -> Dict[str, Any]:
        """获取引擎状态报告"""
        report = {}

        for engine, status in self.engine_status.items():
            report[engine.value] = {
                'available': status.available,
                'last_check': time.strftime('%Y-%m-%d %H:%M:%S',
                                            time.localtime(status.last_check_time)),
                'success_rate': status.success_rate,
                'average_response_time': status.average_response_time,
                'error_message': status.error_message
            }

        return report
