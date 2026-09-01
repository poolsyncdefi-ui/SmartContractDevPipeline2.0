# src/persistence/project_state.py

"""
Project state management for the Smart Contract Dev Pipeline.
F26 – src/persistence/project_state.py

Rôle Fonctionnel : Gestionnaire d'etat permettant de synchroniser les taches et logs avec la base de donnees.
Ce module fournit une interface CRUD complete pour la gestion de l'etat
des projets, sprints et resultats de taches. Il supporte:
- La creation, lecture, mise a jour et suppression des sprints
- La sauvegarde et recuperation des resultats de taches
- La recherche avancee avec filtres
- La mise en cache des donnees
- Les transactions BDD
- Les statistiques de performance

Le ProjectState est utilise par le WorkflowEngine et les agents
pour persister l'etat des executions.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, and_, or_, func, desc
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Optional, Any, Union, Tuple
from datetime import datetime, timedelta
import logging
import json
from functools import wraps

# Import des modules du pipeline
from src.persistence.models_orm import Project, Sprint, TaskResult, Artifact
from src.core.models import Sprint as SprintModel, TaskResult as TaskResultModel
from src.core.exceptions import PipelineError
from src.config.settings import settings

# Configuration du logging
logger = logging.getLogger(__name__)


def handle_db_errors(func):
    """
    Decorateur pour la gestion des erreurs BDD.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except SQLAlchemyError as e:
            logger.error(f"Database error in {func.__name__}: {str(e)}")
            await args[0].session.rollback() if hasattr(args[0], 'session') else None
            raise PipelineError(f"Database error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
            raise
    return wrapper


class ProjectState:
    """
    Interface CRUD pour l'etat du projet.
    
    Cette classe fournit toutes les operations necessaires pour
    gerer l'etat des projets, sprints et resultats.
    
    Attributes:
        session (AsyncSession): Session SQLAlchemy
        cache_enabled (bool): Activer la mise en cache
        _cache (Dict): Cache des donnees
        _cache_ttl (int): Duree de vie du cache (secondes)
    """
    
    def __init__(
        self,
        session: AsyncSession,
        cache_enabled: bool = True,
        cache_ttl: int = 60
    ):
        """
        Initialise le gestionnaire d'etat.
        
        Args:
            session: Session SQLAlchemy
            cache_enabled: Activer la mise en cache (defaut: True)
            cache_ttl: Duree de vie du cache en secondes (defaut: 60)
        """
        self.session = session
        self.cache_enabled = cache_enabled
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Dict] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._stats = {
            "queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }
        
        logger.info("ProjectState initialized")
    
    # =========================================================================
    # GESTION DU CACHE
    # =========================================================================
    
    def _get_cache_key(self, prefix: str, **kwargs) -> str:
        """
        Genere une cle de cache.
        
        Args:
            prefix: Prefixe de la cle
            **kwargs: Parametres de la cle
            
        Returns:
            str: Cle de cache
        """
        key_parts = [prefix]
        for k, v in sorted(kwargs.items()):
            key_parts.append(f"{k}:{v}")
        return ":".join(key_parts)
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """
        Verifie si une entree de cache est valide.
        
        Args:
            cache_key: Cle de cache
            
        Returns:
            bool: True si valide
        """
        if cache_key not in self._cache_timestamps:
            return False
        age = (datetime.utcnow() - self._cache_timestamps[cache_key]).total_seconds()
        return age < self.cache_ttl
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """
        Recupere une donnee du cache.
        
        Args:
            cache_key: Cle de cache
            
        Returns:
            Optional[Any]: Donnee cachee ou None
        """
        if not self.cache_enabled:
            return None
        
        if self._is_cache_valid(cache_key):
            self._stats["cache_hits"] += 1
            return self._cache.get(cache_key)
        
        self._stats["cache_misses"] += 1
        return None
    
    def _set_cache(self, cache_key: str, data: Any) -> None:
        """
        Stocke une donnee dans le cache.
        
        Args:
            cache_key: Cle de cache
            data: Donnee a stocker
        """
        if not self.cache_enabled:
            return
        
        self._cache[cache_key] = data
        self._cache_timestamps[cache_key] = datetime.utcnow()
    
    def _invalidate_cache(self, prefix: Optional[str] = None) -> None:
        """
        Invalide le cache.
        
        Args:
            prefix: Prefixe des cles a invalider (optionnel)
        """
        if prefix is None:
            self._cache.clear()
            self._cache_timestamps.clear()
        else:
            keys_to_remove = [
                k for k in self._cache.keys()
                if k.startswith(prefix)
            ]
            for key in keys_to_remove:
                del self._cache[key]
                if key in self._cache_timestamps:
                    del self._cache_timestamps[key]
    
    # =========================================================================
    # GESTION DES SPRINTS
    # =========================================================================
    
    @handle_db_errors
    async def create_sprint(self, sprint: SprintModel) -> SprintModel:
        """
        Cree un nouveau sprint.
        
        Args:
            sprint: Donnees du sprint
            
        Returns:
            SprintModel: Sprint cree
            
        Raises:
            ValueError: Si les donnees sont invalides
            PipelineError: Si l'insertion echoue
        """
        if not sprint.name:
            raise ValueError("Sprint name is required")
        if not sprint.project_id:
            raise ValueError("Project ID is required")
        
        # Verification de l'existence du projet
        project = await self.get_project(sprint.project_id)
        if not project:
            raise ValueError(f"Project {sprint.project_id} not found")
        
        # Creation du sprint BDD
        db_sprint = Sprint(
            id=sprint.id or str(datetime.utcnow().timestamp()),
            project_id=sprint.project_id,
            name=sprint.name,
            description=sprint.description,
            status=sprint.status or "planned",
            start_date=sprint.start_date,
            end_date=sprint.end_date,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.session.add(db_sprint)
        await self.session.commit()
        await self.session.refresh(db_sprint)
        
        # Invalidation du cache
        self._invalidate_cache(f"sprint:{sprint.project_id}")
        
        logger.info(f"Sprint created: {db_sprint.id} ({db_sprint.name})")
        
        return self._to_sprint_model(db_sprint)
    
    @handle_db_errors
    async def get_sprint(self, sprint_id: str) -> Optional[SprintModel]:
        """
        Recupere un sprint par ID.
        
        Args:
            sprint_id: ID du sprint
            
        Returns:
            Optional[SprintModel]: Sprint ou None
        """
        self._stats["queries"] += 1
        
        # Verification du cache
        cache_key = self._get_cache_key("sprint", id=sprint_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Requete BDD
        stmt = select(Sprint).where(Sprint.id == sprint_id)
        result = await self.session.execute(stmt)
        db_sprint = result.scalar_one_or_none()
        
        if db_sprint:
            sprint_model = self._to_sprint_model(db_sprint)
            self._set_cache(cache_key, sprint_model)
            return sprint_model
        
        return None
    
    @handle_db_errors
    async def update_sprint(self, sprint_id: str, data: Dict) -> SprintModel:
        """
        Met a jour un sprint.
        
        Args:
            sprint_id: ID du sprint
            data: Donnees a mettre a jour
            
        Returns:
            SprintModel: Sprint mis a jour
            
        Raises:
            ValueError: Si le sprint n'existe pas
        """
        # Verification de l'existence
        stmt = select(Sprint).where(Sprint.id == sprint_id)
        result = await self.session.execute(stmt)
        db_sprint = result.scalar_one_or_none()
        
        if not db_sprint:
            raise ValueError(f"Sprint {sprint_id} not found")
        
        # Mise a jour des champs
        for key, value in data.items():
            if hasattr(db_sprint, key):
                setattr(db_sprint, key, value)
        
        db_sprint.updated_at = datetime.utcnow()
        
        await self.session.commit()
        await self.session.refresh(db_sprint)
        
        # Invalidation du cache
        self._invalidate_cache(f"sprint:{sprint_id}")
        self._invalidate_cache(f"sprints:{db_sprint.project_id}")
        
        logger.info(f"Sprint updated: {sprint_id}")
        
        return self._to_sprint_model(db_sprint)
    
    @handle_db_errors
    async def delete_sprint(self, sprint_id: str) -> bool:
        """
        Supprime un sprint.
        
        Args:
            sprint_id: ID du sprint
            
        Returns:
            bool: True si supprime
            
        Raises:
            ValueError: Si le sprint n'existe pas
        """
        # Verification de l'existence
        stmt = select(Sprint).where(Sprint.id == sprint_id)
        result = await self.session.execute(stmt)
        db_sprint = result.scalar_one_or_none()
        
        if not db_sprint:
            raise ValueError(f"Sprint {sprint_id} not found")
        
        # Suppression
        await self.session.delete(db_sprint)
        await self.session.commit()
        
        # Invalidation du cache
        self._invalidate_cache(f"sprint:{sprint_id}")
        self._invalidate_cache(f"sprints:{db_sprint.project_id}")
        
        logger.info(f"Sprint deleted: {sprint_id}")
        return True
    
    @handle_db_errors
    async def list_sprints(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[SprintModel]:
        """
        Liste les sprints avec filtres.
        
        Args:
            project_id: Filtrer par projet (optionnel)
            status: Filtrer par statut (optionnel)
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination
            
        Returns:
            List[SprintModel]: Liste des sprints
        """
        self._stats["queries"] += 1
        
        # Construction de la requete
        stmt = select(Sprint)
        
        if project_id:
            stmt = stmt.where(Sprint.project_id == project_id)
        
        if status:
            stmt = stmt.where(Sprint.status == status)
        
        stmt = stmt.order_by(desc(Sprint.created_at))
        stmt = stmt.limit(limit).offset(offset)
        
        result = await self.session.execute(stmt)
        db_sprints = result.scalars().all()
        
        return [self._to_sprint_model(s) for s in db_sprints]
    
    @handle_db_errors
    async def get_project_sprints(
        self,
        project_id: str,
        status: Optional[str] = None
    ) -> List[SprintModel]:
        """
        Recupere tous les sprints d'un projet.
        
        Args:
            project_id: ID du projet
            status: Filtrer par statut (optionnel)
            
        Returns:
            List[SprintModel]: Liste des sprints
        """
        return await self.list_sprints(project_id=project_id, status=status)
    
    # =========================================================================
    # GESTION DES RESULTATS
    # =========================================================================
    
    @handle_db_errors
    async def save_task_result(self, result: TaskResultModel) -> TaskResultModel:
        """
        Sauvegarde le resultat d'une tache.
        
        Args:
            result: Resultat de la tache
            
        Returns:
            TaskResultModel: Resultat sauvegarde
            
        Raises:
            ValueError: Si les donnees sont invalides
        """
        if not result.task_id:
            raise ValueError("Task ID is required")
        if not result.sprint_id:
            raise ValueError("Sprint ID is required")
        if not result.status:
            raise ValueError("Status is required")
        
        # Verification de l'existence du sprint
        sprint = await self.get_sprint(result.sprint_id)
        if not sprint:
            raise ValueError(f"Sprint {result.sprint_id} not found")
        
        # Creation du resultat BDD
        db_result = TaskResult(
            id=result.id or f"res_{datetime.utcnow().timestamp()}",
            sprint_id=result.sprint_id,
            task_id=result.task_id,
            agent_id=result.agent_id,
            status=result.status,
            output=result.output,
            error=result.error,
            duration=result.duration,
            timestamp=result.timestamp or datetime.utcnow()
        )
        
        self.session.add(db_result)
        await self.session.commit()
        await self.session.refresh(db_result)
        
        # Invalidation du cache
        self._invalidate_cache(f"task_results:{result.sprint_id}")
        self._invalidate_cache(f"task_result:{result.task_id}")
        
        logger.info(f"Task result saved: {db_result.id} ({db_result.task_id})")
        
        return self._to_task_result_model(db_result)
    
    @handle_db_errors
    async def get_task_result(self, task_result_id: str) -> Optional[TaskResultModel]:
        """
        Recupere un resultat de tache par ID.
        
        Args:
            task_result_id: ID du resultat
            
        Returns:
            Optional[TaskResultModel]: Resultat ou None
        """
        self._stats["queries"] += 1
        
        # Verification du cache
        cache_key = self._get_cache_key("task_result", id=task_result_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Requete BDD
        stmt = select(TaskResult).where(TaskResult.id == task_result_id)
        result = await self.session.execute(stmt)
        db_result = result.scalar_one_or_none()
        
        if db_result:
            result_model = self._to_task_result_model(db_result)
            self._set_cache(cache_key, result_model)
            return result_model
        
        return None
    
    @handle_db_errors
    async def get_task_results(
        self,
        sprint_id: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TaskResultModel]:
        """
        Recupere les resultats de taches.
        
        Args:
            sprint_id: Filtrer par sprint (optionnel)
            task_id: Filtrer par tache (optionnel)
            status: Filtrer par statut (optionnel)
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination
            
        Returns:
            List[TaskResultModel]: Liste des resultats
        """
        self._stats["queries"] += 1
        
        # Construction de la requete
        stmt = select(TaskResult)
        
        if sprint_id:
            stmt = stmt.where(TaskResult.sprint_id == sprint_id)
        
        if task_id:
            stmt = stmt.where(TaskResult.task_id == task_id)
        
        if status:
            stmt = stmt.where(TaskResult.status == status)
        
        stmt = stmt.order_by(desc(TaskResult.timestamp))
        stmt = stmt.limit(limit).offset(offset)
        
        result = await self.session.execute(stmt)
        db_results = result.scalars().all()
        
        return [self._to_task_result_model(r) for r in db_results]
    
    @handle_db_errors
    async def get_latest_task_result(
        self,
        task_id: str
    ) -> Optional[TaskResultModel]:
        """
        Recupere le dernier resultat d'une tache.
        
        Args:
            task_id: ID de la tache
            
        Returns:
            Optional[TaskResultModel]: Dernier resultat ou None
        """
        results = await self.get_task_results(
            task_id=task_id,
            limit=1,
            offset=0
        )
        return results[0] if results else None
    
    @handle_db_errors
    async def get_task_results_by_status(
        self,
        sprint_id: str,
        status: str
    ) -> List[TaskResultModel]:
        """
        Recupere les resultats d'un sprint par statut.
        
        Args:
            sprint_id: ID du sprint
            status: Statut a filtrer
            
        Returns:
            List[TaskResultModel]: Liste des resultats
        """
        return await self.get_task_results(sprint_id=sprint_id, status=status)
    
    # =========================================================================
    # GESTION DES PROJETS
    # =========================================================================
    
    @handle_db_errors
    async def create_project(
        self,
        name: str,
        description: str = "",
        config: Optional[Dict] = None
    ) -> Project:
        """
        Cree un nouveau projet.
        
        Args:
            name: Nom du projet
            description: Description du projet
            config: Configuration du projet
            
        Returns:
            Project: Projet cree
        """
        if not name:
            raise ValueError("Project name is required")
        
        db_project = Project(
            id=str(datetime.utcnow().timestamp()),
            name=name,
            description=description,
            config=config or {},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        self.session.add(db_project)
        await self.session.commit()
        await self.session.refresh(db_project)
        
        logger.info(f"Project created: {db_project.id} ({db_project.name})")
        
        return db_project
    
    @handle_db_errors
    async def get_project(self, project_id: str) -> Optional[Project]:
        """
        Recupere un projet par ID.
        
        Args:
            project_id: ID du projet
            
        Returns:
            Optional[Project]: Projet ou None
        """
        self._stats["queries"] += 1
        
        # Verification du cache
        cache_key = self._get_cache_key("project", id=project_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Requete BDD
        stmt = select(Project).where(Project.id == project_id)
        result = await self.session.execute(stmt)
        db_project = result.scalar_one_or_none()
        
        if db_project:
            self._set_cache(cache_key, db_project)
        
        return db_project
    
    @handle_db_errors
    async def update_project(
        self,
        project_id: str,
        data: Dict
    ) -> Project:
        """
        Met a jour un projet.
        
        Args:
            project_id: ID du projet
            data: Donnees a mettre a jour
            
        Returns:
            Project: Projet mis a jour
            
        Raises:
            ValueError: Si le projet n'existe pas
        """
        stmt = select(Project).where(Project.id == project_id)
        result = await self.session.execute(stmt)
        db_project = result.scalar_one_or_none()
        
        if not db_project:
            raise ValueError(f"Project {project_id} not found")
        
        for key, value in data.items():
            if hasattr(db_project, key):
                setattr(db_project, key, value)
        
        db_project.updated_at = datetime.utcnow()
        
        await self.session.commit()
        await self.session.refresh(db_project)
        
        # Invalidation du cache
        self._invalidate_cache(f"project:{project_id}")
        
        logger.info(f"Project updated: {project_id}")
        
        return db_project
    
    @handle_db_errors
    async def list_projects(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> List[Project]:
        """
        Liste tous les projets.
        
        Args:
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination
            
        Returns:
            List[Project]: Liste des projets
        """
        self._stats["queries"] += 1
        
        stmt = select(Project).order_by(desc(Project.created_at))
        stmt = stmt.limit(limit).offset(offset)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    # =========================================================================
    # GESTION DES ARTEFACTS
    # =========================================================================
    
    @handle_db_errors
    async def save_artifact(
        self,
        artifact_type: str,
        content: str,
        metadata: Optional[Dict] = None,
        task_id: Optional[str] = None,
        name: Optional[str] = None
    ) -> Artifact:
        """
        Sauvegarde un artefact.
        
        Args:
            artifact_type: Type d'artefact
            content: Contenu de l'artefact
            metadata: Metadonnees (optionnel)
            task_id: ID de la tache (optionnel)
            name: Nom de l'artefact (optionnel)
            
        Returns:
            Artifact: Artefact sauvegarde
        """
        db_artifact = Artifact(
            id=f"art_{datetime.utcnow().timestamp()}",
            type=artifact_type,
            name=name or f"{artifact_type}_{datetime.utcnow().timestamp()}",
            content=content,
            metadata=metadata or {},
            task_id=task_id,
            created_at=datetime.utcnow()
        )
        
        self.session.add(db_artifact)
        await self.session.commit()
        await self.session.refresh(db_artifact)
        
        logger.info(f"Artifact saved: {db_artifact.id} ({db_artifact.type})")
        
        return db_artifact
    
    @handle_db_errors
    async def get_artifacts(
        self,
        task_id: Optional[str] = None,
        artifact_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Artifact]:
        """
        Recupere les artefacts.
        
        Args:
            task_id: Filtrer par tache (optionnel)
            artifact_type: Filtrer par type (optionnel)
            limit: Nombre maximum de resultats
            
        Returns:
            List[Artifact]: Liste des artefacts
        """
        stmt = select(Artifact)
        
        if task_id:
            stmt = stmt.where(Artifact.task_id == task_id)
        
        if artifact_type:
            stmt = stmt.where(Artifact.type == artifact_type)
        
        stmt = stmt.order_by(desc(Artifact.created_at))
        stmt = stmt.limit(limit)
        
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================
    
    @handle_db_errors
    async def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        """
        Recupere les statistiques d'un projet.
        
        Args:
            project_id: ID du projet
            
        Returns:
            Dict: Statistiques du projet
        """
        # Nombre de sprints
        sprints = await self.list_sprints(project_id=project_id)
        
        # Nombre de resultats
        results = await self.get_task_results(sprint_id=project_id)
        
        # Statistiques par statut
        status_counts = {}
        for result in results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1
        
        # Duree totale
        total_duration = sum(r.duration or 0 for r in results)
        
        return {
            "project_id": project_id,
            "total_sprints": len(sprints),
            "total_tasks": len(results),
            "status_counts": status_counts,
            "total_duration": total_duration,
            "success_rate": (
                status_counts.get("SUCCESS", 0) / len(results) if results else 0
            )
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du ProjectState.
        
        Returns:
            Dict: Statistiques
        """
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "cache_hit_rate": (
                self._stats["cache_hits"] / (self._stats["cache_hits"] + self._stats["cache_misses"])
                if self._stats["cache_hits"] + self._stats["cache_misses"] > 0
                else 0
            )
        }
    
    # =========================================================================
    # METHODES UTILITAIRES
    # =========================================================================
    
    def _to_sprint_model(self, db_sprint: Sprint) -> SprintModel:
        """
        Convertit un Sprint BDD en SprintModel.
        
        Args:
            db_sprint: Sprint BDD
            
        Returns:
            SprintModel: Sprint model
        """
        return SprintModel(
            id=db_sprint.id,
            project_id=db_sprint.project_id,
            name=db_sprint.name,
            description=db_sprint.description,
            status=db_sprint.status,
            start_date=db_sprint.start_date,
            end_date=db_sprint.end_date,
            created_at=db_sprint.created_at,
            updated_at=db_sprint.updated_at
        )
    
    def _to_task_result_model(self, db_result: TaskResult) -> TaskResultModel:
        """
        Convertit un TaskResult BDD en TaskResultModel.
        
        Args:
            db_result: TaskResult BDD
            
        Returns:
            TaskResultModel: TaskResult model
        """
        return TaskResultModel(
            id=db_result.id,
            sprint_id=db_result.sprint_id,
            task_id=db_result.task_id,
            agent_id=db_result.agent_id,
            status=db_result.status,
            output=db_result.output,
            error=db_result.error,
            duration=db_result.duration,
            timestamp=db_result.timestamp
        )
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<ProjectState(session={id(self.session)}, cache_size={len(self._cache)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le ProjectState en dictionnaire.
        
        Returns:
            Dict: Representation
        """
        return {
            "cache_enabled": self.cache_enabled,
            "cache_size": len(self._cache),
            "cache_ttl": self.cache_ttl,
            "stats": self._stats
        }