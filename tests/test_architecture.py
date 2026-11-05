"""架构约束测试（不连库，进 CI）：把分层/边界规则从注释升级为可执行断言。

覆盖五条硬规则：
1. domain 不依赖任何框架（fastapi/starlette/sqlalchemy/redis/celery/asyncpg），
   也不 import 本上下文的 application/infrastructure/interfaces（不向外依赖）；
2. application 不 import infrastructure / interfaces（依赖倒置方向固定）；
3. infrastructure 不 import interfaces（适配器不入站）；
4. 跨上下文 import 只允许 interfaces 层，且目标只能是对方的 interfaces
   或对方 application/ports.py（已发布语言）；
5. reputation 任何层不得 import qa（事件边界靠 DTO，不靠类型耦合）。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = REPO_ROOT / "app"

_FRAMEWORK_ROOTS = ("fastapi", "starlette", "sqlalchemy", "redis", "celery", "asyncpg")
_LAYERS = ("domain", "application", "infrastructure", "interfaces")
_OUTWARD_LAYERS = ("application", "infrastructure", "interfaces")


def _imports(path: Path) -> list[str]:
    """模块内全部 import 点（含函数体内 import，避免延迟导入成为逃逸口）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.append(node.module)
    return found


def _modules() -> list[tuple[Path, list[str]]]:
    return [
        (path, _imports(path))
        for path in sorted(APP_ROOT.rglob("*.py"))
        if path.name != "__init__.py"
    ]


def _parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(APP_ROOT).parts


def _context(path: Path) -> str | None:
    parts = _parts(path)
    if len(parts) > 2 and parts[0] == "contexts":
        return parts[1]
    return None


def _layer(path: Path) -> str | None:
    if _context(path) is None:
        return None
    return next((part for part in _parts(path) if part in _LAYERS), None)


def _context_target(module: str) -> tuple[str, tuple[str, ...]] | None:
    """app.contexts.<ctx>.<rest> → (ctx, rest)；非上下文模块返回 None。"""
    prefix = "app.contexts."
    if not module.startswith(prefix):
        return None
    rest = module[len(prefix) :].split(".")
    if len(rest) < 2:
        return None
    return rest[0], tuple(rest[1:])


def test_domain_is_framework_free_and_closed() -> None:
    for path, modules in _modules():
        if _layer(path) != "domain":
            continue
        context = _context(path)
        for module in modules:
            assert not module.startswith(
                _FRAMEWORK_ROOTS
            ), f"domain 不得依赖框架: {path} → {module}"
            target = _context_target(module)
            if target is None or target[0] != context:
                continue
            assert target[1][0] not in _OUTWARD_LAYERS, (
                f"domain 不得向外依赖: {path} → {module}"
            )


def test_application_does_not_import_adapters() -> None:
    for path, modules in _modules():
        if _layer(path) != "application":
            continue
        for module in modules:
            assert ".infrastructure" not in module, (
                f"application 不得依赖基础设施: {path} → {module}"
            )
            assert ".interfaces" not in module, f"application 不得依赖接口层: {path} → {module}"


def test_infrastructure_does_not_import_interfaces() -> None:
    for path, modules in _modules():
        if _layer(path) != "infrastructure":
            continue
        for module in modules:
            assert ".interfaces" not in module, f"基础设施不得依赖接口层: {path} → {module}"


def test_cross_context_imports_are_interfaces_only() -> None:
    for path, modules in _modules():
        context = _context(path)
        if context is None:
            continue
        for module in modules:
            target = _context_target(module)
            if target is None or target[0] == context:
                continue
            assert _layer(path) == "interfaces", (
                f"跨上下文依赖只允许在 interfaces 层: {path} → {module}"
            )
            rest = target[1]
            allowed = rest[:1] == ("interfaces",) or rest[:2] == ("application", "ports")
            assert allowed, f"跨上下文目标不在允许清单: {path} → {module}"


def test_reputation_never_imports_qa() -> None:
    for path, modules in _modules():
        if _context(path) != "reputation":
            continue
        for module in modules:
            assert not module.startswith(
                "app.contexts.qa"
            ), f"reputation 必须对 qa 零 import: {path} → {module}"
