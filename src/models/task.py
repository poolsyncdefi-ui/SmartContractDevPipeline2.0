# src/models/task.py
from sqlalchemy import Column, String, ForeignKey, Integer, JSON, Enum
from sqlalchemy.orm import relationship
from src.db.database import Base
from src.models.project import ProjectStatus
import enum

class TaskState(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AUTO_TESTING = "AUTO_TESTING"
    WAITING_HUMAN_VALIDATION = "WAITING_HUMAN_VALIDATION"
    SUCCESS = "SUCCESS"
    CIRCUIT_BROKEN = "CIRCUIT_BROKEN"

class TaskModel(Base):
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"))
    state = Column(Enum(TaskState), default=TaskState.PENDING)
    dependencies = Column(JSON, default=[])
    retry_count = Column(Integer, default=0)
    
    # Relation avec le projet
    project = relationship("ProjectModel", back_populates="tasks")
    
    def is_executable(self, completed_task_ids: set) -> bool:
        """Vérifie si toutes les dépendances sont satisfaites."""
        return set(self.dependencies).issubset(completed_task_ids)
    
    def increment_retry(self) -> int:
        """Incrémente le compteur de tentatives."""
        self.retry_count += 1
        return self.retry_count