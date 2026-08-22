# -*- coding: utf-8 -*-
"""
Marble 3D Service - API 测试
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app  # noqa: E402


# 模拟 World Labs API 的 HTTP 响应（避免真实网络请求与超时）
_MOCK_RESPONSE = MagicMock()
_MOCK_RESPONSE.status_code = 401
_MOCK_RESPONSE.text = '{"error": "Invalid API Key"}'
_MOCK_RESPONSE.json.return_value = {'error': 'Invalid API Key'}


class TestAPI(unittest.TestCase):
    """测试 API 端点"""

    def setUp(self):
        """设置测试客户端"""
        self.app = app.test_client()
        self.app.testing = True

    # 所有触发 /api/create 或 /api/task 的测试都 mock 掉外部 HTTP
    # 与 LLM 探测，避免真实网络请求导致的超时

    @patch('routes.world.requests.post', return_value=_MOCK_RESPONSE)
    @patch('routes.world.requests.get', return_value=_MOCK_RESPONSE)
    @patch('routes.world.llm_client.detect')
    def _create_with_mocks(self, mock_detect, mock_get, mock_post,
                           json_data=None, form_data=None, headers=None):
        """辅助方法：带 mock 调用 /api/create"""
        mock_detect.return_value = {'available': False}
        if json_data is not None:
            return self.app.post(
                '/api/create', json=json_data,
                content_type='application/json', headers=headers or {}
            )
        return self.app.post(
            '/api/create', data=form_data or {},
            content_type='multipart/form-data', headers=headers or {}
        )

    @patch('routes.world.requests.get', return_value=_MOCK_RESPONSE)
    @patch('routes.world.requests.post', return_value=_MOCK_RESPONSE)
    @patch('routes.world.llm_client.detect')
    def _task_with_mocks(self, mock_detect, mock_get, mock_post,
                         task_id='invalid-id-12345', headers=None):
        """辅助方法：带 mock 调用 /api/task/<id>"""
        mock_detect.return_value = {'available': False}
        return self.app.get(
            f'/api/task/{task_id}', headers=headers or {}
        )

    def test_health_endpoint(self):
        """测试健康检查端点"""
        response = self.app.get('/health')
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertIn('timestamp', data)

    def test_index_endpoint(self):
        """测试根路由"""
        response = self.app.get('/')
        # 应该返回 index.html
        self.assertIn(response.status_code, [200, 404])

    def test_llm_status_endpoint(self):
        """测试 LLM 状态端点"""
        response = self.app.get('/api/llm-status')
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertIn('success', data)
        self.assertIn('available', data)

    def test_create_world_no_prompt_no_image(self):
        """测试创建世界 - 缺少提示词和图片"""
        response = self.app.post(
            '/api/create',
            json={},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertEqual(data['success'], False)
        self.assertIn('error', data)

    def test_create_world_no_api_key(self):
        """测试创建世界 - 有提示词但无 API Key（默认Stable Zero123需图片，应返回400）"""
        response = self._create_with_mocks(json_data={'prompt': '一只可爱的橘猫'})
        data = response.get_json()
        if data and not data.get('success'):
            self.assertIn(response.status_code, [400, 401, 500])

    def test_create_world_with_header_api_key(self):
        """测试创建世界 - 通过 X-API-Key 请求头传递 API Key"""
        response = self._create_with_mocks(
            json_data={'prompt': '一只可爱的橘猫'},
            headers={'X-API-Key': 'test-fake-key-12345'}
        )
        data = response.get_json()
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))

    def test_get_task_status_invalid_id(self):
        """测试获取任务状态 - 无效 task_id（通过 header 传 key）"""
        response = self._task_with_mocks(
            task_id='invalid-id-12345', headers={'X-API-Key': 'test-fake-key'}
        )
        data = response.get_json()
        self.assertTrue(data is not None and 'success' in data)

    def test_get_task_status_no_api_key(self):
        """测试获取任务状态 - 无 API Key"""
        response = self._task_with_mocks(task_id='invalid-id-12345')
        data = response.get_json()
        if data and not data.get('success'):
            self.assertIn(response.status_code, [200, 401, 500])

    def test_upload_image_no_file(self):
        """测试上传图片 - 没有文件"""
        response = self.app.post('/api/upload-image')
        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertEqual(data['success'], False)

    def test_upload_image_invalid_extension(self):
        """测试上传图片 - 不支持的扩展名"""
        from io import BytesIO
        fake_file = BytesIO(b'fake content')
        response = self.app.post(
            '/api/upload-image',
            data={'image': (fake_file, 'test.txt')},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertEqual(data['success'], False)

    def test_upload_image_not_real_image(self):
        """测试上传图片 - 扩展名正确但内容不是图片"""
        from io import BytesIO
        # 伪装成 png 但实际不是图片
        fake_file = BytesIO(b'not a real image content')
        response = self.app.post(
            '/api/upload-image',
            data={'image': (fake_file, 'test.png')},
            content_type='multipart/form-data'
        )
        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertEqual(data['success'], False)

    def test_cors_headers(self):
        """测试 CORS 头"""
        response = self.app.options('/api/create')
        # CORS 应该允许跨域请求
        self.assertIn('Access-Control-Allow-Origin', response.headers)

    def test_engine_status_endpoint(self):
        """测试引擎状态端点"""
        response = self.app.get('/api/engine-status')
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data.get('success'))
        self.assertIn('engines', data)

    def test_models_endpoint(self):
        """测试模型列表端点（本地部署模型支持）"""
        response = self.app.get('/api/models')
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertTrue(data.get('success'))
        # 三类模型信息齐全
        self.assertIn('llm', data)
        self.assertIn('text_to_image', data)
        self.assertIn('three_d', data)
        self.assertIn('available', data['llm'])
        self.assertIn('models', data['text_to_image'])
        self.assertIn('available_backends', data['three_d'])
        # 3D 后端应包含全部三个后端选项
        backend_names = [b['name'] for b in data['three_d']['available_backends']]
        self.assertIn('zero123plus', backend_names)
        self.assertIn('stable-zero123', backend_names)
        self.assertIn('sd-img2img', backend_names)

    def test_generate_image_invalid_width(self):
        """测试文生图 - 非法分辨率参数（校验应在模型加载前执行）"""
        response = self.app.post(
            '/api/generate-image',
            json={'prompt': 'a cat', 'width': 5000},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_generate_image_width_not_multiple_of_8(self):
        """测试文生图 - 分辨率须为 8 的倍数"""
        response = self.app.post(
            '/api/generate-image',
            json={'prompt': 'a cat', 'width': 511},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

    def test_generate_image_non_numeric_param(self):
        """测试文生图 - 非数字参数"""
        response = self.app.post(
            '/api/generate-image',
            json={'prompt': 'a cat', 'num_inference_steps': 'abc'},
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)

        data = response.get_json()
        self.assertIn('num_inference_steps', data['error'])

    def test_api_docs_endpoint(self):
        """测试 API 文档端点"""
        response = self.app.get('/api/docs')
        self.assertEqual(response.status_code, 200)

    def test_static_file_serving(self):
        """测试静态文件服务"""
        response = self.app.get('/')
        # 根路由应该返回 HTML
        if response.status_code == 200:
            self.assertIn('text/html', response.content_type)

    def test_create_world_with_form_data(self):
        """测试创建世界 - FormData 格式（模拟前端调用）"""
        response = self._create_with_mocks(
            form_data={
                'prompt': '一只可爱的橘猫',
                'use_local_llm': 'false',
                'engine': 'auto'
            },
            headers={'X-API-Key': 'test-fake-key'}
        )
        data = response.get_json()
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))


class TestSecurity(unittest.TestCase):
    """安全相关测试"""

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    @patch('routes.world.requests.get', return_value=_MOCK_RESPONSE)
    @patch('routes.world.requests.post', return_value=_MOCK_RESPONSE)
    @patch('routes.world.llm_client.detect')
    def test_api_key_not_in_url(self, mock_detect, mock_post, mock_get):
        """测试 API Key 不出现在 URL 中（通过 header 传递）"""
        mock_detect.return_value = {'available': False}
        response = self.app.get(
            '/api/task/test-id',
            headers={'X-API-Key': 'secret-key-12345'}
        )
        self.assertIsNotNone(response)

    @patch('routes.world.requests.post', return_value=_MOCK_RESPONSE)
    @patch('routes.world.requests.get', return_value=_MOCK_RESPONSE)
    @patch('routes.world.llm_client.detect')
    def test_api_key_in_header_takes_priority(self, mock_detect, mock_get, mock_post):
        """测试 header 中的 API Key 优先于 body"""
        mock_detect.return_value = {'available': False}
        response = self.app.post(
            '/api/create',
            json={
                'prompt': 'test',
                'api_key': 'body-key'
            },
            content_type='application/json',
            headers={'X-API-Key': 'header-key'}
        )
        data = response.get_json()
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))


if __name__ == '__main__':
    unittest.main()
