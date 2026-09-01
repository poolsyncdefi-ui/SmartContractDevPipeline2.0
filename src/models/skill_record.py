# src/models/skill_record.py
from sqlalchemy import Column, String, Text, JSON
from src.db.database import Base

class SkillRecordModel(Base):
    __tablename__ = "skill_records"
    
    skill_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    prompt_rules = Column(Text, nullable=False)
    input_schema_json = Column(JSON, nullable=False)
    python_code = Column(Text, nullable=True)  # Code de la compétence (optionnel)
    
    def to_dict(self) -> dict:
        """Retourne les métadonnées principales de la compétence."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "prompt_rules": self.prompt_rules[:100] + "..." if len(self.prompt_rules) > 100 else self.prompt_rules
        }