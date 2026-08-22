# -*- coding: utf-8 -*-
"""
通用本地 LLM 客户端
支持任意 OpenAI 兼容端点（LM Studio / vLLM / llama.cpp / 自定义）以及 Ollama 原生协议
所有配置通过环境变量注入，见 .env.example 的「本地 LLM 配置」部分
"""

import os
import time
import logging
import threading

import requests

logger = logging.getLogger(__name__)

# OpenAI 兼容风格的提供方（/models 列模型，/chat/completions 对话）
OPENAI_STYLE_PROVIDERS = {'lmstudio', 'vllm', 'llamacpp', 'openai-compatible'}

# 提供方默认 base_url（OpenAI 风格须含 /v1）
_DEFAULT_BASE_URLS = {
    'lmstudio': 'http://localhost:1234/v1',
    'vllm': 'http://localhost:8000/v1',
    'llamacpp': 'http://localhost:8080/v1',
    'ollama': 'http://localhost:11434',
}

PROBE_TIMEOUT = 2  # 探测超时（秒）

SYSTEM_PROMPT = """你是一个 3D 世界生成专家。用户的中文描述会被翻译成英文，并添加细节让 3D 场景更生动。

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


class LocalLLMClient:
    """通用本地 LLM 客户端

    探测结果缓存 60 秒：探测需同步请求各端点（各 2s 超时），
    不缓存时每次请求最坏引入数秒延迟。
    """

    CHECK_TTL = 60  # 秒

    def __init__(self):
        self.provider = os.environ.get('LLM_PROVIDER', 'auto').strip().lower() or 'auto'
        self.base_url = os.environ.get('LLM_BASE_URL', '').strip().rstrip('/')
        self.model = os.environ.get('LLM_MODEL', '').strip()
        self.temperature = float(os.environ.get('LLM_TEMPERATURE', '0.7'))
        self.timeout = int(os.environ.get('LLM_TIMEOUT', '30'))

        self._cache = {'expires': 0.0, 'result': None}
        self._lock = threading.Lock()

    # ===== 探测 =====
    def detect(self, force_refresh=False):
        """探测可用的本地 LLM。

        返回 dict：
            {available, provider, base_url, model, models}
        不可用时 available=False 并附 reason。
        """
        if not force_refresh:
            with self._lock:
                if self._cache['result'] is not None and time.time() < self._cache['expires']:
                    return self._cache['result']

        result = self._detect_uncached()
        with self._lock:
            self._cache['result'] = result
            self._cache['expires'] = time.time() + self.CHECK_TTL
        return result

    def _detect_uncached(self):
        if self.provider == 'auto':
            # 优先级：自定义 LLM_BASE_URL → LM Studio → Ollama
            candidates = []
            if self.base_url:
                candidates.append(('openai-compatible', self.base_url))
            candidates.append(('lmstudio', self._lmstudio_url()))
            candidates.append(('ollama', self._ollama_url()))
            for provider, url in candidates:
                info = self._probe(provider, url)
                if info['available']:
                    return info
            return {'available': False, 'reason': '未检测到本地 LLM 服务'}

        # 显式指定提供方
        url = self.base_url or self._default_url(self.provider)
        if not url:
            return {
                'available': False,
                'reason': f'LLM_PROVIDER={self.provider} 需要设置 LLM_BASE_URL',
            }
        return self._probe(self.provider, url)

    def _probe(self, provider, url):
        """探测单个端点并返回探测信息"""
        try:
            if provider == 'ollama':
                r = requests.get(f'{url}/api/tags', timeout=PROBE_TIMEOUT)
                if r.status_code == 200:
                    models = [
                        m.get('name') or m.get('model')
                        for m in (r.json().get('models') or [])
                    ]
                    models = [m for m in models if m]
                    if not models:
                        return {'available': False, 'reason': 'Ollama 无已安装模型'}
                    model = self._pick_model(models)
                    return self._info(True, provider, url, model, models)
            else:
                r = requests.get(f'{url}/models', timeout=PROBE_TIMEOUT)
                if r.status_code == 200:
                    data = r.json() or {}
                    models = [
                        m.get('id') for m in (data.get('data') or []) if m.get('id')
                    ]
                    model = self._pick_model(models)
                    return self._info(True, provider, url, model, models)
        except Exception as e:
            logger.debug(f"探测 {provider} ({url}) 失败: {e}")
        return {'available': False, 'reason': f'{provider} ({url}) 不可达'}

    def _info(self, available, provider, url, model, models):
        logger.info(f"检测到本地 LLM: {provider} ({url}), 模型: {model}")
        return {
            'available': available,
            'provider': provider,
            'base_url': url,
            'model': model,
            'models': models,
        }

    def _pick_model(self, models):
        """从模型列表选择模型：优先 LLM_MODEL 配置，否则取第一个"""
        if self.model:
            if not models or self.model in models:
                return self.model
            logger.warning(
                f"LLM_MODEL={self.model} 不在可用列表 {models[:5]}，回退到第一个模型"
            )
        if models:
            return models[0]
        return 'local-model'  # LM Studio 等接受任意模型名

    def _default_url(self, provider):
        if provider == 'lmstudio':
            return self._lmstudio_url()
        if provider == 'ollama':
            return self._ollama_url()
        return _DEFAULT_BASE_URLS.get(provider)

    @staticmethod
    def _lmstudio_url():
        return (os.environ.get('LM_STUDIO_URL') or 'http://localhost:1234/v1').rstrip('/')

    @staticmethod
    def _ollama_url():
        return (os.environ.get('OLLAMA_URL') or 'http://localhost:11434').rstrip('/')

    # ===== 提示词优化 =====
    def enhance_prompt(self, prompt, model_override=None):
        """使用本地 LLM 优化提示词。

        返回 (enhanced_prompt | None, provider | None)
        """
        info = self.detect()
        if not info['available']:
            return None, None

        model = model_override or info['model']
        if model_override and info.get('models') and model_override not in info['models']:
            logger.warning(f"指定的 llm_model={model_override} 不在可用列表，使用默认 {info['model']}")
            model = info['model']

        try:
            if info['provider'] == 'ollama':
                enhanced = self._chat_ollama(info['base_url'], model, prompt)
            else:
                enhanced = self._chat_openai(info['base_url'], model, prompt)
        except Exception as e:
            logger.warning(f"本地 LLM 调用失败: {e}")
            return None, None

        if enhanced:
            logger.info(
                f"本地 LLM 提示词优化成功 [{info['provider']}/{model}]: {prompt[:50]}..."
            )
            return enhanced, info['provider']
        return None, None

    def _chat_openai(self, base_url, model, prompt):
        """OpenAI 兼容 /chat/completions（LM Studio / vLLM / llama.cpp 等）"""
        response = requests.post(
            f'{base_url}/chat/completions',
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': prompt},
                ],
                'temperature': self.temperature,
                'max_tokens': 200,
            },
            timeout=self.timeout,
        )
        if response.status_code == 200:
            return (response.json()['choices'][0]['message']['content'] or '').strip()
        logger.warning(f"LLM HTTP {response.status_code}: {response.text[:200]}")
        return None

    def _chat_ollama(self, base_url, model, prompt):
        """Ollama 原生 /api/chat"""
        response = requests.post(
            f'{base_url}/api/chat',
            json={
                'model': model,
                'messages': [
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': prompt},
                ],
                'stream': False,
                'options': {'temperature': self.temperature},
            },
            timeout=self.timeout,
        )
        if response.status_code == 200:
            return (response.json().get('message', {}).get('content') or '').strip()
        logger.warning(f"Ollama HTTP {response.status_code}: {response.text[:200]}")
        return None
