"""Database schema and session management utilities."""

from __future__ import annotations

import enum
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    create_engine,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base class with consistent naming conventions."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _utcnow() -> datetime:
    """Return a timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


class TimestampMixin:
    """Mixin that adds creation and update timestamps to models."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class JobStatus(str, enum.Enum):
    """Enumeration describing the lifecycle of a compression job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class DatabaseConfig:
    """Configuration container used for initialising the SQLAlchemy engine."""

    url: str
    echo: bool = False
    pool_pre_ping: bool = True
    connect_args: Mapping[str, Any] | None = None

    def engine_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments accepted by :func:`sqlalchemy.create_engine`."""

        kwargs: dict[str, Any] = {"echo": self.echo, "pool_pre_ping": self.pool_pre_ping}
        if self.connect_args is not None:
            kwargs["connect_args"] = dict(self.connect_args)
        return kwargs


def create_engine_from_config(config: DatabaseConfig) -> Engine:
    """Create an SQLAlchemy :class:`Engine` using the provided configuration."""

    return create_engine(config.url, **config.engine_kwargs())


SessionFactory = sessionmaker[Session]


def configure_session_factory(engine: Engine) -> SessionFactory:
    """Create a configured session factory bound to *engine*."""

    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


class SessionManager(AbstractContextManager[Session]):
    """Context manager that controls session lifecycle and commit semantics."""

    def __init__(self, factory: SessionFactory):
        self._factory = factory
        self._session: Session | None = None

    def __enter__(self) -> Session:
        self._session = self._factory()
        return self._session

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        if self._session is None:
            return False

        try:
            if exc_type is None:
                self._session.commit()
            else:
                self._session.rollback()
        finally:
            self._session.close()
            self._session = None
        return False

    @property
    def session(self) -> Session:
        """Return the active session or raise a clear error if unavailable."""

        if self._session is None:
            raise RuntimeError("Session has not been entered yet.")
        return self._session


class User(TimestampMixin, Base):
    """Application user with authentication and relationship metadata."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    jobs: Mapped[list["CompressionJob"]] = relationship(
        "CompressionJob",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class CompressionJob(TimestampMixin, Base):
    """Represents a request to compress a PDF document."""

    __tablename__ = "compression_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    compressed_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    compression_level: Mapped[str] = mapped_column(String(20), nullable=False)
    preserve_images: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False, length=20),
        nullable=False,
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="jobs")


__all__ = [
    "Base",
    "CompressionJob",
    "DatabaseConfig",
    "JobStatus",
    "SessionManager",
    "TimestampMixin",
    "User",
    "configure_session_factory",
    "create_engine_from_config",
]
