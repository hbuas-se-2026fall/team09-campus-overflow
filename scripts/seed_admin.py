"""幂等初始化或提权管理员账号（F15 运维脚本）。

从环境变量读取信息（绝不硬编码密码）：
- ADMIN_EMAIL：管理员邮箱
- ADMIN_PASSWORD：管理员明文密码（须满足密码强度不变式：≥8 位且含字母与数字）
- ADMIN_STAFF_ID：管理员登录工号（格式 T+4~8 位数字，用于 POST /api/v1/auth/login）
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少必需环境变量 {name}")
    return value


async def seed_admin() -> None:
    from app.contexts.identity.domain.user import User, validate_password_strength
    from app.contexts.identity.domain.value_objects import Email, StaffId
    from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
    from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
    from app.shared.engine import engine, session_factory

    email = _require_env("ADMIN_EMAIL")
    password = _require_env("ADMIN_PASSWORD")
    staff_id = _require_env("ADMIN_STAFF_ID")

    Email(email)
    StaffId(staff_id)
    validate_password_strength(password)

    try:
        async with session_factory() as session:
            repo = SqlAlchemyUserRepository(session)
            by_email = await repo.get_by_email(email)
            by_staff = await repo.get_by_staff_id(staff_id)
            if by_email is not None and by_staff is not None and by_email.id != by_staff.id:
                raise RuntimeError("ADMIN_EMAIL 与 ADMIN_STAFF_ID 分属不同既有用户，拒绝提权")

            existing = by_email or by_staff
            if existing is not None:
                if existing.role == "admin":
                    print(f"管理员已就绪（幂等跳过）：user_id={existing.id}")
                    return
                promoted = await repo.update_role(existing.id, "admin")
                await session.commit()
                print(f"已将既有用户提权为管理员：user_id={promoted.id}")
                return

            password_hash = await BcryptPasswordHasher().hash(password)
            user = User.register(
                role="teacher",
                email_value=email,
                password_hash_value=password_hash,
                identity_value=staff_id,
            )
            await repo.add(user)
            promoted = await repo.update_role(user.id, "admin")
            await session.commit()
            print(f"已创建管理员账号：user_id={promoted.id}")
    finally:
        await engine.dispose()


def main() -> int:
    try:
        asyncio.run(seed_admin())
    except Exception as exc:
        print(f"seed_admin 失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
