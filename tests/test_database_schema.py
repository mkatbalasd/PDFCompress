from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

from pdfcompress.database import (
    Base,
    CompressionJob,
    DatabaseConfig,
    JobStatus,
    SessionManager,
    User,
    configure_session_factory,
    create_engine_from_config,
)


@pytest.fixture()
def in_memory_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_metadata_defines_expected_tables(in_memory_engine: object) -> None:
    inspector = inspect(in_memory_engine)
    assert set(inspector.get_table_names()) == {"users", "compression_jobs"}


def test_user_and_job_relationship(in_memory_engine: object) -> None:
    factory = sessionmaker(bind=in_memory_engine, expire_on_commit=False)

    with factory() as session:
        user = User(email="user@example.com", full_name="Test User", hashed_password="secret")
        session.add(user)
        session.flush()

        job = CompressionJob(
            user_id=user.id,
            original_filename="report.pdf",
            original_size_bytes=1024,
            compression_level="medium",
        )
        session.add(job)
        session.commit()

    with factory() as session:
        stored_job = session.query(CompressionJob).one()
        assert stored_job.user.email == "user@example.com"
        assert stored_job.status is JobStatus.QUEUED
        assert stored_job.preserve_images is False

        session.delete(stored_job.user)
        session.commit()

    with factory() as session:
        assert session.query(CompressionJob).count() == 0


def test_session_manager_handles_commit_and_rollback(in_memory_engine: object) -> None:
    factory = configure_session_factory(in_memory_engine)
    manager = SessionManager(factory)

    with manager as session:
        session.add(User(email="unique@example.com", full_name="Unique", hashed_password="secret"))

    with pytest.raises(IntegrityError):
        with manager as session:
            session.add(User(email="unique@example.com", full_name="Duplicate", hashed_password="secret"))

    with manager as session:
        assert session.query(User).count() == 1


def test_database_config_creates_engine() -> None:
    config = DatabaseConfig(url="sqlite:///:memory:", echo=True, connect_args={"check_same_thread": False})
    engine = create_engine_from_config(config)

    assert str(engine.url) == "sqlite:///:memory:"
    assert engine.echo is True

    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert "users" in inspector.get_table_names()
