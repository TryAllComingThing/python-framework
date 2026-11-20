"""File metadata response contracts."""

from pydantic import BaseModel


class FileUploadResponse(BaseModel):
    id: int
    name: str
    size: int
    sha256: str


class FileDeleteResponse(BaseModel):
    deleted: bool


class FileMetadataResponse(BaseModel):
    id: int
    name: str
    size: int
    sha256: str
    content_type: str
