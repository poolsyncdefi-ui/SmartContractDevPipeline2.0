# src/persistence/models_orm.py
from sqlalchemy import Column, String, JSON, DateTime, Integer, Float, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime
import uuid

Base = declarative_base()

class Project(Base):
    __tablename__ = 'projects'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(String)
    chain = Column(String, default='ethereum')
    config = Column(JSON)  # stocke ProjectConfig en JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Sprint(Base):
    __tablename__ = 'sprints'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String, ForeignKey('projects.id'))
    name = Column(String, nullable=False)
    status = Column(String, default='planned')
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TaskResult(Base):
    __tablename__ = 'task_results'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sprint_id = Column(String, ForeignKey('sprints.id'))
    task_id = Column(String, nullable=False)
    agent_id = Column(String)
    status = Column(String)
    output = Column(JSON)
    error = Column(String)
    duration = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

class Artifact(Base):
    __tablename__ = 'artifacts'
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String)  # solidity, test, doc, etc.
    content = Column(Text)  # texte
    metadata = Column(JSON)
    vector = Column(Text)  # stocké en string pour simplifier (ou utiliser pgvector)
    created_at = Column(DateTime, default=datetime.utcnow)