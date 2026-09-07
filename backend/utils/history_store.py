# -*- coding: utf-8 -*-
"""
生成历史存储
JSON 文件持久化（backend/data/history.json），线程安全。
每条记录引用的文件会被上传清理守护线程豁免，避免画廊缩略图失效。
"""

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HISTORY_FILE = os.path.join(DATA_DIR, 'history.json')

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load() -> List[Dict[str, Any]]:
    """读取全部历史（调用方需持锁或仅在锁内使用）"""
    _ensure_dir()
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"历史文件读取失败，重置为空: {e}")
        return []


def _save(entries: List[Dict[str, Any]]):
    _ensure_dir()
    tmp = HISTORY_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_FILE)  # 原子替换，避免写一半损坏


def record(kind: str, prompt: str, engine: str = '',
           status: str = 'completed', payload: Dict[str, Any] = None,
           files: List[str] = None, task_id: str = '') -> Dict[str, Any]:
    """新增一条历史记录，返回带 id 的完整记录。

    Args:
        kind: 't2i' | 'three_d' | 'world'
        payload: 展示与重开所需的数据（image_url / view_urls / world_id 等）
        files: 需要清理豁免的文件路径列表（相对 uploads/ 或
               generated_3d_views/ 的路径，或 uploads/ 内文件名）
    """
    entry = {
        'id': uuid.uuid4().hex[:12],
        'kind': kind,
        'prompt': (prompt or '')[:200],
        'engine': engine,
        'status': status,
        'task_id': task_id,
        'payload': payload or {},
        'files': files or [],
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    with _lock:
        entries = _load()
        entries.insert(0, entry)  # 新的在前
        _save(entries[:500])     # 上限 500 条
    return entry


def update_by_task_id(task_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按 task_id 更新记录（World Labs 任务完成时回填结果），返回更新后的记录"""
    if not task_id:
        return None
    with _lock:
        entries = _load()
        for entry in entries:
            if entry.get('task_id') == task_id:
                entry.update(patch)
                entry['payload'] = {**(entry.get('payload') or {}), **patch.get('payload', {})}
                if patch.get('files'):
                    entry['files'] = list(
                        set(entry.get('files') or []) | set(patch['files'])
                    )
                _save(entries)
                return entry
    return None


def list_entries(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    with _lock:
        entries = _load()
    total = len(entries)
    return {
        'total': total,
        'entries': entries[offset:offset + limit],
    }


def delete_entry(entry_id: str, delete_files: bool = True) -> bool:
    """删除一条记录；delete_files=True 时同时删除其引用的生成文件"""
    with _lock:
        entries = _load()
        remaining = []
        removed = None
        for entry in entries:
            if entry['id'] == entry_id and removed is None:
                removed = entry
            else:
                remaining.append(entry)
        if removed is None:
            return False
        _save(remaining)

    if delete_files and removed:
        from routes.world import UPLOAD_DIR, GENERATED_3D_DIR  # 延迟导入避免循环
        for rel in removed.get('files') or []:
            rel = (rel or '').lstrip('/')
            if rel.startswith('uploads/'):
                path = os.path.join(UPLOAD_DIR, rel[len('uploads/'):])
            elif rel.startswith('generated_3d_views/'):
                path = os.path.join(GENERATED_3D_DIR, rel[len('generated_3d_views/'):])
            else:
                continue
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                logger.warning(f"删除历史文件失败 {path}: {e}")
    return True


def referenced_files() -> set:
    """返回所有历史记录引用的文件名集合（uploads/ 内的 basename），
    供上传清理守护线程豁免。"""
    with _lock:
        entries = _load()
    referenced = set()
    for entry in entries:
        for rel in entry.get('files') or []:
            referenced.add(os.path.basename(rel))
    return referenced
