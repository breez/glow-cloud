from pydantic import BaseModel, Field


class ReceiveRequest(BaseModel):
    amount_sats: int | None = Field(default=None, ge=1)
    description: str = Field(default="", max_length=639)


class SendRequest(BaseModel):
    destination: str = Field(min_length=1, max_length=2000)
    amount_sats: int | None = Field(default=None, ge=1)


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(default=["balance", "receive"])
    budget_sats: int | None = Field(default=None, ge=1)
    budget_period: str | None = Field(default=None, pattern="^(daily|weekly|monthly)$")
    max_amount_sats: int | None = Field(default=None, ge=1)


class ApiKeyRecord(BaseModel):
    id: str
    name: str
    max_amount_sats: int | None
    budget_sats: int | None
    budget_period: str | None
    permissions: list[str]
