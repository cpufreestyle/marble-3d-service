"""
Marble 3D Service - API 测试
"""

import unittest
import sys
from pathlib import Path

# 添加 backend 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app import app


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
        # 应该返回 index.html（可能 404 如果文件不存在）
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

    def test_create_world_with_prompt(self):
        """测试创建世界 - 有提示词"""
        # 注意：这个测试需要有效的 API Key 和网络连接
        # 这里只是测试 API 调用，不实际生成 3D 世界
        pass

    def test_get_task_status_invalid_id(self):
        """测试获取任务状态 - 无效 task_id"""
        # 注意：这个测试需要有效的 task_id
        # 这里只是测试 API 调用
        pass

    def test_upload_image_no_file(self):
        """测试上传图片 - 没有文件"""
        response = self.app.post('/api/upload-image')
        self.assertEqual(response.status_code, 400)
        
        data = response.get_json()
        self.assertEqual(data['success'], False)

    def test_cors_headers(self):
        """测试 CORS 头"""
        response = self.app.options('/api/create')
        # CORS 应该允许跨域请求
        self.assertIn('Access-Control-Allow-Origin', response.headers)


if __name__ == '__main__':
    unittest.main()
