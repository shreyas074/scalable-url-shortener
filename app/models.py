from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from .database import Base


class URL(Base):
    """
    A shortened URL record.

    short_code: the 7-char base62 code used in redirect links (unique, indexed)
    original_url: the destination the code redirects to
    created_at: for TTL / expiry policies down the line
    """

    __tablename__ = "urls"

    id = Column(Integer, primary_key=True, index=True)
    short_code = Column(String(10), unique=True, index=True, nullable=False)
    original_url = Column(String(2048), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    clicks = relationship("Click", back_populates="url", cascade="all, delete-orphan")


class Click(Base):
    """
    One row per redirect event. Kept separate from URL so analytics writes
    never block or lock the URL table, and so this table can later be
    swapped for a time-series store (e.g. DynamoDB with TTL, or Kinesis
    -> S3) without touching the URL table at all.
    """

    __tablename__ = "clicks"

    id = Column(Integer, primary_key=True, index=True)
    url_id = Column(Integer, ForeignKey("urls.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    referrer = Column(String(512), nullable=True)
    ip_hash = Column(String(64), nullable=True)  # hashed, never raw IP

    url = relationship("URL", back_populates="clicks")
