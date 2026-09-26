import sys

from app.core.config import get_settings
from app.core.errors import AppError
from app.services.validators import mask_phone


class FakeSmsVerificationProvider:
    name = "fake"

    async def send_code(
        self,
        *,
        phone: str,
        code: str,
        purpose: str,
        expires_in_seconds: int,
    ) -> str | None:
        environment = get_settings().app_environment.strip().lower()
        if environment not in {"development", "test"}:
            raise AppError(
                503,
                "SMS_PROVIDER_NOT_CONFIGURED",
                "生产环境禁止使用模拟短信服务",
            )
        minutes = max(1, expires_in_seconds // 60)
        sys.stderr.write(
            f"[DEV SMS] {mask_phone(phone)} 验证码 {code}，{minutes} 分钟内有效\n"
        )
        sys.stderr.flush()
        return None
