# -*- coding: utf-8 -*-
import requests
import io

BASE = "http://127.0.0.1:5000"

print("=" * 60)
print("  Marble 3D Service - API 功能测试")
print("=" * 60)

# 1. 健康检查
print("\n[1] GET /health")
r = requests.get(f"{BASE}/health")
print(f"    Status: {r.status_code}")
print(f"    Body:   {r.json()}")

# 2. 引擎状态
print("\n[2] GET /api/engine-status")
r = requests.get(f"{BASE}/api/engine-status")
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Stable Zero123 available: {d['engines']['stable_3d']['available']}")
print(f"    World Labs available:     {d['engines']['world_labs']['available']}")

# 3. LLM 状态
print("\n[3] GET /api/llm-status")
r = requests.get(f"{BASE}/api/llm-status")
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Available: {d.get('available')}")

# 4. 前端页面
print("\n[4] GET / (前端页面)")
r = requests.get(f"{BASE}/")
print(f"    Status: {r.status_code}")
print(f"    Content-Type: {r.headers.get('Content-Type')}")
print(f"    Size: {len(r.text)} chars")

# 5. API 文档
print("\n[5] GET /api/docs (Swagger)")
r = requests.get(f"{BASE}/api/docs")
print(f"    Status: {r.status_code}")

# 6. 创建世界 - 无参数
print("\n[6] POST /api/create (无参数)")
r = requests.post(f"{BASE}/api/create", json={})
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 7. 创建世界 - 文字模式（默认 Stable Zero123，无图片）
print("\n[7] POST /api/create (文字模式, 无图片)")
r = requests.post(f"{BASE}/api/create", json={"prompt": "a cat"})
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 8. 创建世界 - FormData + Stable Zero123 + 无图片
print("\n[8] POST /api/create (FormData, engine=stable_3d, 无图片)")
r = requests.post(
    f"{BASE}/api/create",
    data={"prompt": "test", "engine": "stable_3d", "use_local_llm": "false"}
)
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 9. 上传图片 - 无文件
print("\n[9] POST /api/upload-image (无文件)")
r = requests.post(f"{BASE}/api/upload-image")
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 10. 上传图片 - 伪造PNG
print("\n[10] POST /api/upload-image (伪造PNG)")
r = requests.post(
    f"{BASE}/api/upload-image",
    files={"image": ("test.png", io.BytesIO(b"fake content"), "image/png")}
)
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 11. 上传图片 - 不支持的扩展名
print("\n[11] POST /api/upload-image (不支持的扩展名)")
r = requests.post(
    f"{BASE}/api/upload-image",
    files={"image": ("test.txt", io.BytesIO(b"hello"), "text/plain")}
)
d = r.json()
print(f"    Status: {r.status_code}")
print(f"    Error:  {d.get('error', 'N/A')}")

# 12. 上传真实图片 → Stable Zero123 生成
print("\n[12] POST /api/create (上传真实图片, Stable Zero123)")
from PIL import Image  # noqa: E402  （延迟导入：仅第 12 项测试需要）
img_buf = io.BytesIO()
Image.new("RGB", (256, 256), color=(100, 150, 200)).save(img_buf, "PNG")
img_buf.seek(0)
r = requests.post(
    f"{BASE}/api/create",
    data={"prompt": "a 3D model", "engine": "stable_3d", "use_local_llm": "false"},
    files={"image": ("test.png", img_buf, "image/png")},
    timeout=300
)
d = r.json()
print(f"    Status: {r.status_code}")
if d.get("success"):
    print(f"    Engine:     {d.get('engine_used')}")
    print(f"    Status:     {d.get('status')}")
    result = d.get("result", {})
    if result.get("view_urls"):
        print(f"    Views:      {len(result['view_urls'])} 个视角")
        print(f"    Time:       {result.get('generation_time', 'N/A')}s")
else:
    print(f"    Error:      {d.get('error', 'N/A')}")
    if d.get("hint"):
        print(f"    Hint:       {d.get('hint')}")

# 13. CORS 头测试
print("\n[13] OPTIONS /api/create (CORS)")
r = requests.options(f"{BASE}/api/create")
print(f"    Status: {r.status_code}")
print(f"    ACAO:   {r.headers.get('Access-Control-Allow-Origin', 'N/A')}")

print("\n" + "=" * 60)
print("  测试完成!")
print("=" * 60)
