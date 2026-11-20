"""Auth request and response contracts; never expose ORM entities."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    csrf_token: str
    user_id: int


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    permissions: list[str]


class LogoutResponse(BaseModel):
    logged_out: bool


class RotateSessionResponse(BaseModel):
    csrf_token: str
