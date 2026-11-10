from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    claim: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    subclaims: Mapped[list["Subclaim"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    sources: Mapped[list["Source"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    verdicts: Mapped[list["Verdict"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Subclaim(Base):
    __tablename__ = "subclaims"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    case: Mapped[Case] = relationship(back_populates="subclaims")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    original_source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    case: Mapped[Case] = relationship(back_populates="sources")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    passage: Mapped[str] = mapped_column(Text)
    locator: Mapped[str] = mapped_column(String(300))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    case: Mapped[Case] = relationship(back_populates="evidence")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    subclaim_id: Mapped[str] = mapped_column(ForeignKey("subclaims.id"))
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    assessment: Mapped[str] = mapped_column(String(20))
    rationale: Mapped[str] = mapped_column(Text)
    case: Mapped[Case] = relationship(back_populates="findings")


class Verdict(Base):
    __tablename__ = "verdicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    text: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    case: Mapped[Case] = relationship(back_populates="verdicts")
    __table_args__ = (UniqueConstraint("case_id", "revision"),)


class Post(Base):
    __tablename__ = "posts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    case: Mapped[Case] = relationship(back_populates="posts")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    traceparent: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    case: Mapped[Case] = relationship(back_populates="jobs")
    __table_args__ = (Index("ix_jobs_status_lease", "status", "lease_until"),)
