"""IAM list and menu response contracts."""

from pydantic import BaseModel


class UserSummaryResponse(BaseModel):
    id: int
    username: str


class MenuResponse(BaseModel):
    id: int
    parent_id: int | None
    name: str
    path: str
    permission: str | None
