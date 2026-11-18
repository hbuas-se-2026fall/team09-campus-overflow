"""邮箱验证码发送适配器（F10）。

- 完整 SMTP 配置（host + from_email 非空，且设 username 时 password 非空）
  → SmtpVerificationCodeSender
- app_env == "prod" 且未配完整 SMTP → UnconfiguredVerificationCodeSender（抛 503，绝不静默打日志）
- app_env in ("dev", "test") 且未配完整 SMTP → DevLogVerificationCodeSender
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config.settings import Settings
from app.contexts.identity.application.ports import VerificationCodeSender
from app.contexts.identity.domain.errors import EmailVerificationUnavailableError

logger = logging.getLogger(__name__)


def is_smtp_configured(settings: Settings) -> bool:
    if not settings.smtp_host.strip() or not settings.smtp_from_email.strip():
        return False
    if settings.smtp_username.strip() and not settings.smtp_password:
        return False
    return True


class SmtpVerificationCodeSender:
    """标准库 smtplib 适配器：放入线程池执行，带显式超时。"""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_email: str,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from_email = from_email
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout_seconds

    def _send_sync(self, recipient: str, code: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = "CampusOverflow 邮箱验证码"
        msg["From"] = self._from_email
        msg["To"] = recipient
        msg.set_content(f"你的 CampusOverflow 邮箱验证码为：{code}（15 分钟内有效）。")
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
            if self._use_tls:
                client.starttls()
            if self._username:
                client.login(self._username, self._password)
            client.send_message(msg)

    async def send(self, email: str, code: str) -> None:
        try:
            await asyncio.to_thread(self._send_sync, email, code)
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            logger.warning("SMTP 发送验证码失败: email=%s", email, exc_info=True)
            raise EmailVerificationUnavailableError("邮件发送失败，请稍后重试") from exc


class DevLogVerificationCodeSender:
    """仅限 dev / test 环境的日志占位发送器。"""

    async def send(self, email: str, code: str) -> None:
        logger.info("开发/测试环境邮箱验证码（未配置 SMTP）: email=%s code=%s", email, code)


class UnconfiguredVerificationCodeSender:
    """生产环境未配完整 SMTP 时的快速失败发送器（503）。"""

    async def send(self, email: str, code: str) -> None:
        raise EmailVerificationUnavailableError("邮件发送服务未配置")


def build_verification_code_sender(settings: Settings) -> VerificationCodeSender:
    if is_smtp_configured(settings):
        return SmtpVerificationCodeSender(
            host=settings.smtp_host.strip(),
            port=settings.smtp_port,
            from_email=settings.smtp_from_email.strip(),
            username=settings.smtp_username.strip(),
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            timeout_seconds=settings.smtp_timeout_seconds,
        )
    if settings.app_env == "prod":
        return UnconfiguredVerificationCodeSender()
    return DevLogVerificationCodeSender()
