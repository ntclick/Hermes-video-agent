"""
Models — Autonomous Content Bridge
SQLAlchemy ORM models for jobs and processing state.
"""
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Float, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    TRANSLATING = "translating"
    RENDERING = "rendering"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    DOUYIN = "douyin"
    OTHER = "other"


class Job(Base):
    """Represents a single video processing job."""
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    platform: Mapped[str] = mapped_column(SAEnum(Platform), default=Platform.OTHER)
    status: Mapped[str] = mapped_column(SAEnum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100

    # Video metadata
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # File paths
    video_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subtitle_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Content
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    translation: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_language: Mapped[str] = mapped_column(String(10), default="vi")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Publishing
    x_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    frames_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    tweet_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tweet_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI Cover Video
    cover_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    ai_scenes_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    script_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Logs
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def append_log(self, message: str):
        """Append a timestamped log entry."""
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        if self.logs:
            self.logs += f"\n{entry}"
        else:
            self.logs = entry

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "platform": self.platform,
            "status": self.status,
            "progress": self.progress,
            "title": self.title,
            "duration": self.duration,
            "thumbnail_url": self.thumbnail_url,
            "target_language": self.target_language,
            "tweet_id": self.tweet_id,
            "tweet_text": self.tweet_text,
            "summary": self.summary,
            "frames_path": self.frames_path,
            "x_account_id": self.x_account_id,
            "cover_path": self.cover_path,
            "ai_scenes_path": self.ai_scenes_path,
            "script_json": self.script_json,
            "logs": self.logs,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

class XAccount(Base):
    """Represents a configured X/Twitter account."""
    __tablename__ = "x_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cookies_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            # NOT sending cookies_json to frontend for security
        }
