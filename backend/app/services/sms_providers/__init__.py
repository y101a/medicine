from app.core.config import get_settings
from app.core.errors import AppError
from app.services.sms_providers.base import SmsVerificationProvider
from app.services.sms_providers.fake import FakeSmsVerificationProvider

_fake_provider = FakeSmsVerificationProvider()


def get_sms_provider() -> SmsVerificationProvider:
    provider = get_settings().sms_provider
    if provider == "fake":
        return _fake_provider
    raise AppError(
        503,
        "SMS_PROVIDER_NOT_CONFIGURED",
        "短信验证服务尚未配置，请稍后再试",
    )


__all__ = ["SmsVerificationProvider", "get_sms_provider"]
