"""共享哨兵类型（F10）：用于在 domain 与 application 间区分“未传”与“显式 None”。"""

from __future__ import annotations

from enum import Enum


class UnsetType(Enum):
    UNSET = "UNSET"


UNSET = UnsetType.UNSET
