from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    data: T
    request_id: str


class FieldViolation(BaseModel):
    field: str
    reason: str


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[FieldViolation] = Field(default_factory=list)


def success(data: T, request_id: str) -> ApiResponse[T]:
    """Build the shared typed success envelope."""
    return ApiResponse[T](data=data, request_id=request_id)
