import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    groups = Column(JSON, nullable=False, default=list)  # e.g. ["HR", "Management", "Engineering"]
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    logs = relationship("AuditLog", back_populates="user")

class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    source_type = Column(String, nullable=False)  # "confluence", "slack", "excel", "pdf"
    filepath = Column(String, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Integer, default=1, nullable=False) # 1 for active, 0 for archived/deleted
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    text_content = Column(Text, nullable=False)
    allowed_groups = Column(JSON, nullable=False, default=lambda: ["Public"])  # e.g. ["HR", "Management"] or ["Public"]
    
    document = relationship("Document", back_populates="chunks")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    retrieved_chunks = Column(JSON, nullable=True)  # List of chunk IDs and document names
    timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    user = relationship("User", back_populates="logs")
