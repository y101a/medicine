from typing import Protocol


class SmsVerificationProvider(Protocol):
    name: str

    async def send_code(
        self,
        *,
        phone: str,
        code: str,
        purpose: str,
        expires_in_seconds: int,
    ) -> str | None: ...
