import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_mainland_phone(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"1[3-9]\d{9}", value):
        raise ValueError("请输入有效的中国大陆手机号")
    return value


class PhoneCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str
    purpose: Literal["registration", "password_reset"]

class PhoneChallengeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    challenge_id: UUID = Field(serialization_alias="challengeId")
    expires_in_seconds: int = Field(serialization_alias="expiresInSeconds")
    resend_after_seconds: int = Field(serialization_alias="resendAfterSeconds")


class PhoneCodeVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    challenge_id: UUID = Field(alias="challengeId")
    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("请输入 6 位数字验证码")
        return value


class PhoneVerificationTokenOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    verification_token: str = Field(serialization_alias="verificationToken")
    expires_in_seconds: int = Field(serialization_alias="expiresInSeconds")


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    phone: str
    verification_token: str = Field(
        alias="verificationToken", min_length=32, max_length=256
    )
    new_password: str = Field(alias="newPassword", min_length=6, max_length=32)
