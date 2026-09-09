# src/persistence/project_state.py

"""
Project state management for the Smart Contract Dev Pipeline.
F26 – src/persistence/project_state.py

Role Fonctionnel : Gestionnaire d'etat permettant de synchroniser les taches et logs avec la base de donnees.
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
from datetime import datetime, timezone, timedelta
import logging
import json
from functools import wraps

# Import des modules du pipeline
from src.persistence.models_orm import (
    ProjectModel,
    TaskModel,
    ExecutionLogModel,
    SkillRecordModel
)
# Modèles Pydantic pour les DTO
from src.core.models import Sprint as SprintDTO, TaskResult as TaskResultDTO
from src.core.exceptions import PipelineError

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
            # Rollback si la session existe
            if args and hasattr(args[0], 'session'):
                try:
                    await args[0].session.rollback()
                except Exception:
                    pass
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
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        
        # Stores d'instance isolés (correction du bug des attributs de classe mutables partagés)
        self._sprint_store: Dict[str, dict] = {}
        self._result_store: Dict[str, dict] = {}
        self._artifact_store: Dict[str, dict] = {}

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
        age = (datetime.now(timezone.utc) - self._cache_timestamps[cache_key]).total_seconds()
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
        self._cache_timestamps[cache_key] = datetime.now(timezone.utc)

    def _invalidate_cache(self, prefix: Optional[str] = None) -> None:
        """
        Invalide le cache de manière robuste.

        Args:
            prefix: Prefixe ou terme des cles a invalider (optionnel)
        """
        if prefix is None:
            self._cache.clear()
            self._cache_timestamps.clear()
        else:
            # Correction du bug d'invalidation rigide : correspondance par début ou inclusion de sous-chaîne
            keys_to_remove = [
                k for k in self._cache.keys()
                if k.startswith(prefix) or prefix in k
            ]
            for key in keys_to_remove:
                del self._cache[key]
                if key in self._cache_timestamps:
                    del self._cache_timestamps[key]

    # =========================================================================
    # GESTION DES PROJETS (modèle ORM ProjectModel)
    # =========================================================================

    @handle_db_errors
    async def create_project(
        self,
        name: str,
        description: str = "",
        config: Optional[Dict] = None,
        project_id: Optional[str] = None
    ) -> ProjectModel:
        """
        Cree un nouveau projet.

        Args:
            name: Nom du projet
            description: Description du projet
            config: Configuration du projet
            project_id: ID optionnel (sinon généré)

        Returns:
            ProjectModel: Projet cree
        """
        if not name:
            raise ValueError("Project name is required")

        db_project = ProjectModel(
            id=project_id or str(datetime.now(timezone.utc).timestamp()),
            name=name,
            description=description,
            spec_yaml=json.dumps(config or {}),
            status="active",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

        self.session.add(db_project)
        await self.session.commit()
        await self.session.refresh(db_project)

        logger.info(f"Project created: {db_project.id} ({db_project.name})")

        return db_project

    @handle_db_errors
    async def get_project(self, project_id: str) -> Optional[ProjectModel]:
        """
        Recupere un projet par ID.

        Args:
            project_id: ID du projet

        Returns:
            Optional[ProjectModel]: Projet ou None
        """
        self._stats["queries"] += 1

        # Verification du cache
        cache_key = self._get_cache_key("project", id=project_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Requete BDD
        stmt = select(ProjectModel).where(ProjectModel.id == project_id)
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
    ) -> ProjectModel:
        """
        Met a jour un projet.

        Args:
            project_id: ID du projet
            data: Donnees a mettre a jour

        Returns:
            ProjectModel: Projet mis a jour

        Raises:
            ValueError: Si le projet n'existe pas
        """
        stmt = select(ProjectModel).where(ProjectModel.id == project_id)
        result = await self.session.execute(stmt)
        db_project = result.scalar_one_or_none()

        if not db_project:
            raise ValueError(f"Project {project_id} not found")

        for key, value in data.items():
            if hasattr(db_project, key):
                setattr(db_project, key, value)

        db_project.updated_at = datetime.now(timezone.utc)

        await self.session.commit()
        await self.session.refresh(db_project)

        # Invalidation du cache
        self._invalidate_cache(project_id)

        logger.info(f"Project updated: {project_id}")

        return db_project

    @handle_db_errors
    async def delete_project(self, project_id: str) -> bool:
        """
        Supprime un projet.

        Args:
            project_id: ID du projet

        Returns:
            bool: True si supprime
        """
        stmt = select(ProjectModel).where(ProjectModel.id == project_id)
        result = await self.session.execute(stmt)
        db_project = result.scalar_one_or_none()

        if not db_project:
            return False

        await self.session.delete(db_project)
        await self.session.commit()

        self._invalidate_cache(project_id)
        logger.info(f"Project deleted: {project_id}")
        return True

    @handle_db_errors
    async def list_projects(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> List[ProjectModel]:
        """
        Liste tous les projets.

        Args:
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination

        Returns:
            List[ProjectModel]: Liste des projets
        """
        self._stats["queries"] += 1

        stmt = select(ProjectModel).order_by(desc(ProjectModel.created_at))
        stmt = stmt.limit(limit).offset(offset)

        result = await self.session.execute(stmt)
        return result.scalars().all()

    # =========================================================================
    # GESTION DES SPRINTS
    # =========================================================================

    @handle_db_errors
    async def create_sprint(self, sprint: SprintDTO) -> SprintDTO:
        """
        Cree un nouveau sprint (stocké en mémoire).

        Args:
            sprint: Donnees du sprint

        Returns:
            SprintDTO: Sprint cree
        """
        if not sprint.name:
            raise ValueError("Sprint name is required")
        if not sprint.project_id:
            raise ValueError("Project ID is required")

        # Verification de l'existence du projet
        project = await self.get_project(sprint.project_id)
        if not project:
            raise ValueError(f"Project {sprint.project_id} not found")

        # Génération d'un ID si absent (gestion sécurisée pour les modèles Pydantic immuables/gelés)
        sprint_id = sprint.id or f"sprint_{datetime.now(timezone.utc).timestamp()}"
        if sprint.id != sprint_id:
            sprint = sprint.model_copy(update={"id": sprint_id})

        # Stockage en mémoire
        sprint_data = sprint.model_dump()
        sprint_data["created_at"] = (sprint.created_at or datetime.now(timezone.utc)).isoformat()
        sprint_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._sprint_store[sprint_id] = sprint_data

        # Invalidation du cache
        self._invalidate_cache(sprint.project_id)

        logger.info(f"Sprint created: {sprint_id} ({sprint.name})")

        return sprint

    @handle_db_errors
    async def get_sprint(self, sprint_id: str) -> Optional[SprintDTO]:
        """
        Recupere un sprint par ID.

        Args:
            sprint_id: ID du sprint

        Returns:
            Optional[SprintDTO]: Sprint ou None
        """
        self._stats["queries"] += 1

        # Verification du cache
        cache_key = self._get_cache_key("sprint", id=sprint_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Recuperation depuis le store mémoire
        sprint_data = self._sprint_store.get(sprint_id)
        if not sprint_data:
            return None

        sprint = SprintDTO(**sprint_data)
        self._set_cache(cache_key, sprint)
        return sprint

    @handle_db_errors
    async def update_sprint(self, sprint_id: str, data: Dict) -> SprintDTO:
        """
        Met a jour un sprint.

        Args:
            sprint_id: ID du sprint
            data: Donnees a mettre a jour

        Returns:
            SprintDTO: Sprint mis a jour

        Raises:
            ValueError: Si le sprint n'existe pas
        """
        if sprint_id not in self._sprint_store:
            raise ValueError(f"Sprint {sprint_id} not found")

        sprint_data = self._sprint_store[sprint_id]
        for key, value in data.items():
            if key in sprint_data:
                sprint_data[key] = value
        sprint_data["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Invalidation du cache
        self._invalidate_cache(sprint_id)
        if sprint_data.get('project_id'):
            self._invalidate_cache(sprint_data.get('project_id'))

        sprint = SprintDTO(**sprint_data)
        logger.info(f"Sprint updated: {sprint_id}")
        return sprint

    @handle_db_errors
    async def delete_sprint(self, sprint_id: str) -> bool:
        """
        Supprime un sprint.

        Args:
            sprint_id: ID du sprint

        Returns:
            bool: True si supprime
        """
        if sprint_id not in self._sprint_store:
            return False

        project_id = self._sprint_store[sprint_id].get("project_id")
        del self._sprint_store[sprint_id]

        self._invalidate_cache(sprint_id)
        if project_id:
            self._invalidate_cache(project_id)

        logger.info(f"Sprint deleted: {sprint_id}")
        return True

    @handle_db_errors
    async def list_sprints(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[SprintDTO]:
        """
        Liste les sprints avec filtres et pagination avec prise en compte correcte du cache.

        Args:
            project_id: Filtrer par projet (optionnel)
            status: Filtrer par statut (optionnel)
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination

        Returns:
            List[SprintDTO]: Liste des sprints
        """
        self._stats["queries"] += 1

        # Construction du cache incluant limit et offset pour éviter le bug de pagination
        cache_key = self._get_cache_key("sprints", project=project_id or "all", status=status or "all", limit=limit, offset=offset)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Filtrage en mémoire
        result = []
        for sprint_data in self._sprint_store.values():
            if project_id and sprint_data.get("project_id") != project_id:
                continue
            if status and sprint_data.get("status") != status:
                continue
            result.append(SprintDTO(**sprint_data))

        # Tri par date de création décroissante
        result.sort(key=lambda s: s.created_at or datetime.min, reverse=True)

        # Pagination
        paginated = result[offset:offset+limit] if limit else result

        self._set_cache(cache_key, paginated)
        return paginated

    @handle_db_errors
    async def get_project_sprints(
        self,
        project_id: str,
        status: Optional[str] = None
    ) -> List[SprintDTO]:
        """
        Recupere tous les sprints d'un projet.

        Args:
            project_id: ID du projet
            status: Filtrer par statut (optionnel)

        Returns:
            List[SprintDTO]: Liste des sprints
        """
        return await self.list_sprints(project_id=project_id, status=status)

    # =========================================================================
    # GESTION DES RESULTATS DE TACHES
    # =========================================================================

    @handle_db_errors
    async def save_task_result(self, result: TaskResultDTO) -> TaskResultDTO:
        """
        Sauvegarde le resultat d'une tache.

        Args:
            result: Resultat de la tache

        Returns:
            TaskResultDTO: Resultat sauvegarde
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

        # Génération d'un ID si absent (gestion sécurisée des modèles Pydantic)
        result_id = result.id or f"res_{datetime.now(timezone.utc).timestamp()}"
        if result.id != result_id:
            result = result.model_copy(update={"id": result_id})

        # Stockage en mémoire
        result_data = result.model_dump()
        result_data["timestamp"] = (result.timestamp or datetime.now(timezone.utc)).isoformat()
        self._result_store[result_id] = result_data

        # Invalidation du cache
        self._invalidate_cache(result.sprint_id)
        self._invalidate_cache(result.task_id)

        logger.info(f"Task result saved: {result_id} ({result.task_id})")

        return result

    @handle_db_errors
    async def get_task_result(self, task_result_id: str) -> Optional[TaskResultDTO]:
        """
        Recupere un resultat de tache par ID.

        Args:
            task_result_id: ID du resultat

        Returns:
            Optional[TaskResultDTO]: Resultat ou None
        """
        self._stats["queries"] += 1

        cache_key = self._get_cache_key("task_result", id=task_result_id)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        result_data = self._result_store.get(task_result_id)
        if not result_data:
            return None

        result = TaskResultDTO(**result_data)
        self._set_cache(cache_key, result)
        return result

    @handle_db_errors
    async def get_task_results(
        self,
        sprint_id: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[TaskResultDTO]:
        """
        Recupere les resultats de taches avec filtres et mise en cache.

        Args:
            sprint_id: Filtrer par sprint (optionnel)
            task_id: Filtrer par tache (optionnel)
            status: Filtrer par statut (optionnel)
            limit: Nombre maximum de resultats
            offset: Offset pour la pagination

        Returns:
            List[TaskResultDTO]: Liste des resultats
        """
        self._stats["queries"] += 1

        cache_key = self._get_cache_key(
            "task_results",
            sprint=sprint_id or "all",
            task=task_id or "all",
            status=status or "all",
            limit=limit,
            offset=offset
        )
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached

        # Filtrage en mémoire
        result = []
        for res_data in self._result_store.values():
            if sprint_id and res_data.get("sprint_id") != sprint_id:
                continue
            if task_id and res_data.get("task_id") != task_id:
                continue
            if status and res_data.get("status") != status:
                continue
            result.append(TaskResultDTO(**res_data))

        # Tri par timestamp décroissant
        result.sort(key=lambda r: r.timestamp or datetime.min, reverse=True)

        paginated = result[offset:offset+limit] if limit else result
        self._set_cache(cache_key, paginated)
        return paginated

    @handle_db_errors
    async def get_latest_task_result(
        self,
        task_id: str
    ) -> Optional[TaskResultDTO]:
        """
        Recupere le dernier resultat d'une tache.

        Args:
            task_id: ID de la tache

        Returns:
            Optional[TaskResultDTO]: Dernier resultat ou None
        """
        results = await self.get_task_results(task_id=task_id, limit=1)
        return results[0] if results else None

    @handle_db_errors
    async def get_task_results_by_status(
        self,
        sprint_id: str,
        status: str
    ) -> List[TaskResultDTO]:
        """
        Recupere les resultats d'un sprint par statut.

        Args:
            sprint_id: ID du sprint
            status: Statut a filtrer

        Returns:
            List[TaskResultDTO]: Liste des resultats
        """
        return await self.get_task_results(sprint_id=sprint_id, status=status)

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
    ) -> dict:
        """
        Sauvegarde un artefact.

        Args:
            artifact_type: Type d'artefact
            content: Contenu de l'artefact
            metadata: Metadonnees (optionnel)
            task_id: ID de la tache (optionnel)
            name: Nom de l'artefact (optionnel)

        Returns:
            dict: Artefact sauvegarde
        """
        artifact_id = f"art_{datetime.now(timezone.utc).timestamp()}"
        artifact_data = {
            "id": artifact_id,
            "type": artifact_type,
            "name": name or f"{artifact_type}_{datetime.now(timezone.utc).timestamp()}",
            "content": content,
            "metadata": metadata or {},
            "task_id": task_id,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        self._artifact_store[artifact_id] = artifact_data

        if task_id:
            self._invalidate_cache(task_id)

        logger.info(f"Artifact saved: {artifact_id} ({artifact_type})")
        return artifact_data

    @handle_db_errors
    async def get_artifacts(
        self,
        task_id: Optional[str] = None,
        artifact_type: Optional[str] = None,
        limit: int = 100
    ) -> List[dict]:
        """
        Recupere les artefacts.

        Args:
            task_id: Filtrer par tache (optionnel)
            artifact_type: Filtrer par type (optionnel)
            limit: Nombre maximum de resultats

        Returns:
            List[dict]: Liste des artefacts
        """
        result = []
        for art_data in self._artifact_store.values():
            if task_id and art_data.get("task_id") != task_id:
                continue
            if artifact_type and art_data.get("type") != artifact_type:
                continue
            result.append(art_data)

        # Tri par date décroissante
        result.sort(key=lambda a: a.get("created_at", ""), reverse=True)
        return result[:limit]

    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================

    @handle_db_errors
    async def get_project_stats(self, project_id: str) -> Dict[str, Any]:
        """
        Recupere les statistiques d'un projet en agrégeant les sprints et résultats.

        Args:
            project_id: ID du projet

        Returns:
            Dict: Statistiques du projet
        """
        sprints = await self.list_sprints(project_id=project_id)

        all_results = []
        for sprint in sprints:
            results = await self.get_task_results(sprint_id=sprint.id)
            all_results.extend(results)

        status_counts = {}
        for result in all_results:
            status_counts[result.status] = status_counts.get(result.status, 0) + 1

        total_duration = sum(getattr(r, 'duration', 0) or 0 for r in all_results)

        return {
            "project_id": project_id,
            "total_sprints": len(sprints),
            "total_tasks": len(all_results),
            "status_counts": status_counts,
            "total_duration": total_duration,
            "success_rate": (
                status_counts.get("SUCCESS", 0) / len(all_results) if all_results else 0
            )
        }

    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du ProjectState.

        Returns:
            Dict: Statistiques
        """
        total_cache_ops = self._stats["cache_hits"] + self._stats["cache_misses"]
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "cache_hit_rate": (
                self._stats["cache_hits"] / total_cache_ops
                if total_cache_ops > 0
                else 0
            )
        }

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
            "stats": self.get_stats()
        }