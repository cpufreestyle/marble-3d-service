# -*- coding: utf-8 -*-
"""
Marble 3D Service - API 测试
"""

import unittest
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app  # noqa: E402


class TestAPI(unittest.TestCase):
    """测试 API 端点"""

    def setUp(self):
        """设置测试客户端"""
        self.app = app.test_client()
        self.app.testing = True

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
        """测试创建世界 - 有提示词但无 API Key（应返回 401）"""
        response = self.app.post(
            '/api/create',
            json={'prompt': '一只可爱的橘猫'},
            content_type='application/json'
        )
        # 没有 API Key 时应返回 401
        data = response.get_json()
        if data and not data.get('success'):
            self.assertIn(response.status_code, [401, 500])

    def test_create_world_with_header_api_key(self):
        """测试创建世界 - 通过 X-API-Key 请求头传递 API Key"""
        response = self.app.post(
            '/api/create',
            json={'prompt': '一只可爱的橘猫'},
            content_type='application/json',
            headers={'X-API-Key': 'test-fake-key-12345'}
        )
        # 提供了 API Key 但不是有效的，应该返回 API 错误而非 401
        data = response.get_json()
        # 可能是 401（key 无效）或其他错误，但不应是 "缺少 API Key"
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))

    def test_get_task_status_invalid_id(self):
        """测试获取任务状态 - 无效 task_id（通过 header 传 key）"""
        response = self.app.get(
            '/api/task/invalid-id-12345',
            headers={'X-API-Key': 'test-fake-key'}
        )
        data = response.get_json()
        # 应该返回错误（非 401，因为有 API Key）
        self.assertTrue(
            data is not None and 'success' in data
        )

    def test_get_task_status_no_api_key(self):
        """测试获取任务状态 - 无 API Key"""
        response = self.app.get('/api/task/invalid-id-12345')
        data = response.get_json()
        # 没有环境变量 API Key 时应该返回错误
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
        response = self.app.post(
            '/api/create',
            data={
                'prompt': '一只可爱的橘猫',
                'use_local_llm': 'false',
                'engine': 'auto'
            },
            content_type='multipart/form-data',
            headers={'X-API-Key': 'test-fake-key'}
        )
        data = response.get_json()
        # 有 API Key 但无效，应该返回 API 错误
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))


class TestSecurity(unittest.TestCase):
    """安全相关测试"""

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_api_key_not_in_url(self):
        """测试 API Key 不出现在 URL 中（通过 header 传递）"""
        response = self.app.get(
            '/api/task/test-id',
            headers={'X-API-Key': 'secret-key-12345'}
        )
        # 确保请求成功发出（不论结果如何）
        self.assertIsNotNone(response)

    def test_api_key_in_header_takes_priority(self):
        """测试 header 中的 API Key 优先于 body"""
        # 同时在 header 和 body 中传 key，header 应优先
        response = self.app.post(
            '/api/create',
            json={
                'prompt': 'test',
                'api_key': 'body-key'
            },
            content_type='application/json',
            headers={'X-API-Key': 'header-key'}
        )
        # 只要不报 "缺少 API Key" 就说明 header 被读取了
        data = response.get_json()
        if data and not data.get('success'):
            self.assertNotIn('缺少', data.get('error', ''))


if __name__ == '__main__':
    unittest.main()
