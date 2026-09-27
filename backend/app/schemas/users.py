import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Gender


class DeleteAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(alias="currentPassword", min_length=6, max_length=32)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    real_name: str | None = Field(default=None, alias="realName", min_length=2, max_length=20)
    gender: Gender | None = None
    username: str | None = Field(default=None, min_length=4, max_length=20)
    current_password: str | None = Field(
        default=None, alias="currentPassword", min_length=6, max_length=32
    )

    @field_validator("real_name", "username", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("real_name")
    @classmethod
    def check_name(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z\u4E00-\u9FFF·]+", value):
            raise ValueError("姓名仅支持中文、英文字母和间隔符 ·")
        return value

    @model_validator(mode="after")
    def check_changes(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("请至少提供一个需要修改的字段")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("姓名、性别、用户名和当前密码不能设为 null")
        if self.username is not None and self.current_password is None:
            raise ValueError("修改用户名需要提供当前密码")
        if self.current_password is not None and self.username is None:
            raise ValueError("当前密码仅在修改用户名时提供")
        return self
