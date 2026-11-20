"""IAM persistence entities; existing table and column contracts are unchanged."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

user_roles = Table(
    "sf_user_roles",
    Base.metadata,
    Column("user_id", ForeignKey("sf_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", ForeignKey("sf_roles.id", ondelete="CASCADE"), primary_key=True),
)
role_permissions = Table(
    "sf_role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("sf_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", ForeignKey("sf_permissions.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    """Account credentials and role assignments."""

    __tablename__ = "sf_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
    auth_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("sf_departments.id", ondelete="SET NULL"), nullable=True
    )
    roles: Mapped[list[Role]] = relationship(secondary=user_roles, lazy="selectin")


Index("ix_sf_users_username_lower", func.lower(User.username), unique=True)


class Role(Base):
    """Permission bundle with explicit enablement and data scope."""

    __tablename__ = "sf_roles"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('SELF', 'DEPARTMENT', 'DEPARTMENT_AND_CHILDREN', 'CUSTOM', 'ALL')",
            name="ck_sf_roles_scope",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    scope: Mapped[str] = mapped_column(
        String(32), default="SELF", server_default=text("'SELF'"), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    permissions: Mapped[list[Permission]] = relationship(
        secondary=role_permissions, lazy="selectin"
    )


class Permission(Base):
    """Named IAM permission code."""

    __tablename__ = "sf_permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(128), unique=True, index=True)


class Department(Base):
    """Hierarchical organizational department."""

    __tablename__ = "sf_departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sf_departments.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))


class RoleDepartment(Base):
    """Role-to-department grant association."""

    __tablename__ = "sf_role_departments"
    role_id: Mapped[int] = mapped_column(
        ForeignKey("sf_roles.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[int] = mapped_column(
        ForeignKey("sf_departments.id", ondelete="CASCADE"), primary_key=True
    )


class Menu(Base):
    """Navigational menu with optional permission binding."""

    __tablename__ = "sf_menus"
    __table_args__ = (UniqueConstraint("path", name="uq_sf_menus_path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sf_menus.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(100))
    path: Mapped[str] = mapped_column(String(255))
    permission_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_num: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
