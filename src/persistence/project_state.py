# src/persistence/project_state.py
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from src.persistence.models_orm import Project, Sprint, TaskResult
from src.core.models import Sprint as SprintModel, TaskResult as TaskResultModel
from typing import List, Dict, Optional

class ProjectState:
    """Interface CRUD pour l'état du projet."""
    
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_sprint(self, sprint: SprintModel) -> SprintModel:
        """Crée un nouveau sprint."""
        # À implémenter
        pass

    async def get_sprint(self, sprint_id: str) -> Optional[SprintModel]:
        """Récupère un sprint par ID."""
        # À implémenter
        pass

    async def update_sprint(self, sprint_id: str, data: Dict) -> SprintModel:
        """Met à jour un sprint."""
        # À implémenter
        pass

    async def save_task_result(self, result: TaskResultModel) -> TaskResultModel:
        """Sauvegarde le résultat d'une tâche."""
        # À implémenter
        pass

    async def get_task_results(self, sprint_id: str) -> List[TaskResultModel]:
        """Récupère tous les résultats d'un sprint."""
        # À implémenter
        pass