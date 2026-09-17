import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.user import Gender, UserRole


class RegisterRequest(BaseModel):
    username: str = Field(min_length=4, max_length=20)
    real_name: str = Field(alias="realName", min_length=2, max_length=20)
    phone: str
    id_card: str = Field(alias="idCard")
    gender: Gender
    password: str = Field(min_length=6, max_length=32)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username_input(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("real_name")
    @classmethod
    def validate_real_name(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z\u4E00-\u9FFF·]+", value):
            raise ValueError("姓名仅支持中文、英文字母和间隔符 ·")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        value = value.strip()
        if len(value) != 11 or not value.isdigit() or value[0] != "1" or value[1] not in "3456789":
            raise ValueError("请输入有效的中国大陆手机号")
        return value

    @field_validator("id_card")
    @classmethod
    def validate_id_card(cls, value: str) -> str:
        from app.services.validators import validate_mainland_id_card

        value = value.strip().upper()
        if not validate_mainland_id_card(value):
            raise ValueError("请输入有效的中国大陆居民身份证号码")
        return value


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=32)


class AuthUser(BaseModel):
    id: UUID
    username: str
    real_name: str = Field(serialization_alias="realName")
    gender: Gender
    role: UserRole
    phone_masked: str = Field(serialization_alias="phoneMasked")
    id_card_masked: str = Field(serialization_alias="idCardMasked")
    registered_at: datetime = Field(serialization_alias="registeredAt")


class AuthResult(BaseModel):
    user: AuthUser
