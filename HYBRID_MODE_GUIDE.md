# 🌍 混合3D世界生成模式指南

本项目现已集成开源Stable Zero123模型，实现混合3D世界生成方案！

## ✨ 新功能特性

### **🤖 智能引擎选择**

- 系统自动根据输入内容选择最佳生成引擎
- 支持图片到3D的本地开源生成（Stable Zero123）
- 保留原有高质量商业API（World Labs）

### **🔧 多种生成模式**

1. **World Labs 模式** （高质量推荐）

   - 支持纯文本和文本+图片生成
   - 生成质量更高，支持复杂场景
   - 需要API Key

2. **Stable Zero123 模式** （开源本地）

   - 仅支持图片到3D生成
   - 完全开源，本地运行
   - 生成多视角3D图像

3. **智能自动模式** （推荐）

   - 系统自动选择最佳引擎
   - 平衡质量和资源消耗
   - 无缝降级机制

## 🚀 使用方法

### **API使用**

#### 基本请求

```bash
POST /api/create
Content-Type: multipart/form-data

# 支持新engine参数
# world_labs: 强制使用World Labs
# stable_3d: 强制使用Stable Zero123 
# auto: 自动选择（默认）

prompt: "一只可爱的橘猫"
image: [图片文件]
engine: "auto"  # 可选: world_labs, stable_3d, auto
```

#### JSON格式

```json
{
  "prompt": "一只可爱的橘猫",
  "image_url": "https://example.com/cat.jpg",
  "engine": "auto"
}
```

### **前端界面更新**

现在前端支持选择生成引擎：

- 🏠 **World Labs**: 高质量云端生成
- 🔓 **Stable Zero123**: 开源本地生成
- 🧠 **自动选择**: 系统智能决策

## 📊 引擎对比

| 特性 | World Labs | Stable Zero123 |
| -------- | -------- | -------- |
| 文本到3D | ✅ 优秀 | ⚠️ 有限 |
| 图片到3D | ✅ 优秀 | ✅ 良好 |
| 生成质量 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 生成速度 | ⭐⭐⭐⭐ | ⭐⭐ |
| 是否需要API | 是 | 否 |
| 本地资源消耗 | 无 | 高（需要4GB+ GPU） |
| 最佳使用场景 | 文本生成、复杂场景 | 图片转3D、隐私保护 |

## 🔧 配置说明

### **环境变量**

#### 必需配置

```bash
WORLD_LABS_API_KEY=your_api_key_here
```

#### 可选配置

```bash
# Stable Zero123配置
STABLE_3D_MODEL_PATH=stabilityai/stable-zero123  # 模型路径
STABLE_3D_OUTPUT_DIR=./generated_3d_views      # 输出目录

# 性能配置
STABLE_3D_NUM_VIEWS=4          # 生成视角数量（1-8）
STABLE_3D_GUIDANCE_SCALE=3.0   # 指导尺度
STABLE_3D_NUM_STEPS=25         # 推理步数
```

### **依赖安装**

#### 核心依赖（已存在）

```bash
cd backend
pip install -r requirements.txt
```

#### 开源模型依赖（可选）

```bash
pip install -r requirements-open-source.txt
```

## 📡 API端点

### 新增端点

#### 获取引擎状态

```text
GET /api/engine-status
```

**响应示例**:

```json
{
  "success": true,
  "engines": {
    "world_labs": {
      "available": true,
      "last_check": "2024-01-01 12:00:00",
      "success_rate": 0.95
    },
    "stable_3d": {
      "available": true,
      "last_check": "2024-01-01 12:00:00",
      "success_rate": 0.80
    }
  },
  "selection_statistics": {
    "total_selections": 42,
    "engine_distribution": {
      "world_labs": 28,
      "stable_3d": 14
    }
  }
}
```

#### 测试Stable Zero123

```text
POST /api/test-stable-3d
```

**用途**: 开发测试，快速验证Stable Zero123功能

### 修改的端点

#### 创建3D世界

```text
POST /api/create
```

**新增参数**:

- `engine`: 指定使用的引擎（world_labs/stable_3d/auto）

**响应增强**:

```json
{
  "success": true,
  "engine_used": "stable-zero123",
  "generation_type": "multi_view_3d",
  "result": {
    "generated_views": [],
    "view_urls": []
  },
  "task_id": "stable3d_abc123",
  "status": "completed"
}
```

## 🛠️ 开发指南

### **本地测试**

```python
# 测试智能选择器
from utils.smart_selector import SmartEngineSelector

selector = SmartEngineSelector()
result = await selector.select_best_engine(
    prompt="一只可爱的橘猫",
    has_image=True,
    user_preference="auto"
)
print(f"选择引擎: {result.selected_engine.value}")
```

### **Stable Zero123集成**

```python
# 测试Stable Zero123
from utils.stable_3d_generator import Stable3DGenerator

generator = Stable3DGenerator()
result = await generator.generate_3d_from_image(
    image, 
    prompt="a cute cat",
    num_views=4
)
```

### **故障排除**

#### Stable Zero123无法加载

- ✅ 确认已安装PyTorch和diffusers
- ✅ 检查GPU内存是否充足（至少4GB）
- ✅ 尝试使用CPU模式（速度较慢）

#### 引擎选择总是返回World Labs

- ✅ 确保系统有足够资源运行Stable Zero123
- ✅ 检查环境变量配置
- ✅ 查看日志了解选择原因

#### 图片生成质量不如预期

- ✅ 尝试调整图片质量和尺寸
- ✅ 使用更具描述性的提示词
- ✅ 切换到World Labs引擎获得更好质量

## 🎯 最佳实践

### **何时使用World Labs**

- 需要高质量3D生成时
- 处理复杂文本描述时
- 生成时间要求严格时
- 商业项目和专业用途

### **何时使用Stable Zero123**

- 需要图片到3D转换时
- 数据隐私保护要求高时
- 开源软件兼容性要求时
- 预算有限或API调用受限时

### **推荐组合策略**

1. **默认使用自动模式** - 让系统智能选择
2. **复杂文本使用World Labs** - 保证质量
3. **图片转换使用Stable Zero123** - 节省成本
4. **监控生成统计** - 优化使用策略

## 📈 性能监控

系统自动记录以下指标：

- 引擎选择频率
- 成功率统计
- 平均响应时间
- 用户偏好分析

访问`/api/engine-status`查看完整报告。

## 🔮 未来计划

### **短期（1-3个月）**

- [ ] 优化Stable Zero123配置参数
- [ ] 添加更多开源模型选项
- [ ] 改进前端Engine选择界面
- [ ] 实现模型性能监控面板

### **中期（3-6个月）**

- [ ] 添加模型微调功能
- [ ] 实现本地模型缓存优化
- [ ] 支持更多图片到3D的开源模型
- [ ] 添加生成质量自动评估

### **长期（6-12个月）**

- [ ] 完全开源版本发布
- [ ] 分布式生成集群支持
- [ ] 个性化模型训练
- [ ] 高级项目管理功能

## 🆘 获取帮助

如果遇到问题，请：

1. 检查日志输出
2. 调用`/api/engine-status`查看详细状态
3. 查看故障排除指南
4. 提交Issue提供详细信息

---

**祝您在混合3D世界生成的新旅程中收获满满！** 🌟
