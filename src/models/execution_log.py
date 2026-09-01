# src/models/execution_log.py
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from src.db.database import Base
import datetime

class ExecutionLogModel(Base):
    __tablename__ = "execution_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String, ForeignKey("tasks.id"))
    agent_id = Column(String, nullable=False)
    prompt_sent = Column(Text)
    raw_response = Column(Text)
    tool_output = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    def format_log_entry(self) -> str:
        """Formate l'entrée de log pour l'affichage."""
        return f"[{self.created_at}] Agent {self.agent_id} on Task {self.task_id}"