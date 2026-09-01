# src/models/project.py
from sqlalchemy import Column, String, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from src.db.database import Base
import datetime
import enum

class ProjectStatus(str, enum.Enum):
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ProjectModel(Base):
    __tablename__ = "projects"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.CREATED)
    spec_yaml = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # Relation avec les tâches
    tasks = relationship("TaskModel", back_populates="project", cascade="all, delete-orphan")
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat()
        }
    
    def update_status(self, new_status: ProjectStatus) -> None:
        self.status = new_status