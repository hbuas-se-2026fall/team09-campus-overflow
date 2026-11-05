"""跨上下文共享的输入校验错误基类。

- 值对象/Pydantic validator → HTTP 层统一映射 422（错误映射在 C2 接入）；
- worker 侧毒载荷不重试：本类是 ValueError 子类，不在 tasks._RETRYABLE 族内，
  与既有「ValueError 不重试」语义完全一致；
- 作为 shared kernel 类型，不 import 任何上下文，避免分层倒挂。
"""

from __future__ import annotations


class DomainValidationError(ValueError):
    """输入不满足领域校验（长度/字符集/格式/取值）。"""
