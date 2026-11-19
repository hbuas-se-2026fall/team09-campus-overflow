class IdentityDomainError(Exception):
    """identity 上下文领域错误基类。"""


class WeakPasswordError(IdentityDomainError):
    """密码不满足强度要求（≥8 位且同时含字母和数字）。"""


class EmailAlreadyExistsError(IdentityDomainError):
    """邮箱已被占用。"""


class IdentityAlreadyExistsError(IdentityDomainError):
    """学号/工号已被占用。"""


class IdentityRequiredError(IdentityDomainError):
    """注册时缺少与角色匹配的校园身份（学号或工号）。"""


class UnknownRoleError(IdentityDomainError):
    """未知的注册角色。"""


class InvalidCredentialsError(IdentityDomainError):
    """登录凭证无效：统一 401，不区分"用户不存在/密码错误"（防枚举）。"""


class AccountLockedError(IdentityDomainError):
    """登录失败超限，账号临时锁定（US-L04，路由层转 423 Locked）。"""


class InvalidRefreshTokenError(IdentityDomainError):
    """Refresh 令牌无效/已失效（路由层转 401，消息按调用点具体化）。"""


class EmailAlreadyVerifiedError(IdentityDomainError):
    """邮箱已完成验证（F10，路由层转 409）。"""


class VerificationCooldownError(IdentityDomainError):
    """验证码发送冷却中（F10，路由层转 429）。"""


class InvalidVerificationCodeError(IdentityDomainError):
    """验证码无效、已过期或尝试次数超限（F10，路由层转 400）。"""


class EmailVerificationUnavailableError(Exception):
    """邮箱验证服务/存储不可用（F10）：故意不继承 IdentityDomainError，防落入基类 422。"""
