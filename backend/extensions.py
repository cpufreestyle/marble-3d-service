# -*- coding: utf-8 -*-
"""
Flask 扩展实例集中管理（避免循环导入）
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
