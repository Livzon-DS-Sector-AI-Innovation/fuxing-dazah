from uuid import UUID
from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"


class SSOCallbackResult(BaseModel):
    token: str
    redirect_url: str


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str | None = None
    mobile: str | None = None
    avatar_url: str | None = None
    employee_no: str | None = None
    department: str | None = None
    position: str | None = None

    model_config = {"from_attributes": True}
