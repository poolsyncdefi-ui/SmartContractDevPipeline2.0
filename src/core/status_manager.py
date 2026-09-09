# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Status Manager
# ==============================================================================
# Fichier: src/core/status_manager.py
# Description: Gestionnaire centralisé pour normaliser et valider les statuts
#              à travers tout le pipeline. Élimine les incohérences typographiques
#              et assure un routage fluide dans le DAG.
# ==============================================================================

from enum import Enum
from typing import Dict, Any, Optional, Set, List, Union
from dataclasses import dataclass, field
import re


# ==============================================================================
# ÉNUMÉRATIONS CENTRALISÉES
# ==============================================================================

class TaskStatus(str, Enum):
    """
    Statuts unifiés pour toutes les tâches du pipeline.
    Tous les statuts sont en minuscules pour garantir la cohérence.
    """
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    AUTO_TESTING = "auto_testing"
    WAITING_HUMAN_VALIDATION = "waiting_human_validation"
    SUCCESS = "success"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class AgentStatus(str, Enum):
    """
    Statuts unifiés pour tous les agents.
    """
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CIRCUIT_OPEN = "circuit_open"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class WorkflowStatus(str, Enum):
    """
    Statuts unifiés pour les workflows.
    """
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ==============================================================================
# STATUS MANAGER
# ==============================================================================

class StatusManager:
    """
    Gestionnaire centralisé pour normaliser et valider les statuts.
    
    Features:
    - Normalisation des statuts (majuscules -> minuscules)
    - Validation des statuts par rapport aux enumérations
    - Conversion entre différents types de statuts
    - Métriques d'utilisation des statuts
    """
    
    # Mappings pour la normalisation des statuts historiques
    STATUS_MAPPINGS = {
        # Anciens statuts en majuscules -> statuts normalisés
        "SUCCESS": TaskStatus.SUCCESS.value,
        "FAILED": TaskStatus.FAILED.value,
        "PENDING": TaskStatus.PENDING.value,
        "RUNNING": TaskStatus.RUNNING.value,
        "CIRCUIT_OPEN": TaskStatus.CIRCUIT_BROKEN.value,
        "CIRCUIT_BROKEN": TaskStatus.CIRCUIT_BROKEN.value,
        "CANCELLED": TaskStatus.CANCELLED.value,
        "BLOCKED": TaskStatus.BLOCKED.value,
        "SKIPPED": TaskStatus.SKIPPED.value,
        "READY": TaskStatus.READY.value,
        "AUTO_TESTING": TaskStatus.AUTO_TESTING.value,
        "WAITING_HUMAN_VALIDATION": TaskStatus.WAITING_HUMAN_VALIDATION.value,
        
        # Anciens statuts d'agents
        "IDLE": AgentStatus.IDLE.value,
        "COMPLETED": AgentStatus.COMPLETED.value,
        "CIRCUIT_OPEN": AgentStatus.CIRCUIT_OPEN.value,
        "PAUSED": AgentStatus.PAUSED.value,
    }
    
    # Statuts terminaux (une tâche dans cet état est considérée comme terminée)
    TERMINAL_STATUSES = {
        TaskStatus.SUCCESS.value,
        TaskStatus.FAILED.value,
        TaskStatus.CIRCUIT_BROKEN.value,
        TaskStatus.CANCELLED.value,
        TaskStatus.SKIPPED.value,
    }
    
    # Statuts d'échec
    FAILURE_STATUSES = {
        TaskStatus.FAILED.value,
        TaskStatus.CIRCUIT_BROKEN.value,
    }
    
    # Statuts nécessitant une intervention humaine
    HUMAN_STATUSES = {
        TaskStatus.WAITING_HUMAN_VALIDATION.value,
    }
    
    def __init__(self):
        """Initialise le gestionnaire de statuts avec des métriques."""
        self._metrics = {
            "normalizations": 0,
            "validations": 0,
            "validation_failures": 0,
            "conversions": 0,
            "by_status": {status.value: 0 for status in TaskStatus}
        }
        self._normalization_history: List[Dict[str, str]] = []
    
    # ==========================================================================
    # MÉTHODES DE NORMALISATION
    # ==========================================================================
    
    @classmethod
    def normalize_status(cls, status: Union[str, Enum]) -> str:
        """
        Normalise un statut vers son équivalent en minuscules.
        
        Args:
            status: Statut à normaliser (str ou Enum)
            
        Returns:
            str: Statut normalisé en minuscules
        """
        if isinstance(status, Enum):
            status = status.value
        
        if not isinstance(status, str):
            return str(status).lower()
        
        # Vérifier si le statut est déjà normalisé
        normalized = status.lower()
        
        # Appliquer les mappings pour les cas particuliers
        if status in cls.STATUS_MAPPINGS:
            return cls.STATUS_MAPPINGS[status]
        
        # Si c'est un statut de TaskStatus valide, le retourner
        if normalized in TaskStatus._value2member_map_:
            return normalized
        
        # Si c'est un statut d'AgentStatus valide, le retourner
        if normalized in AgentStatus._value2member_map_:
            return normalized
        
        # Si c'est un statut de WorkflowStatus valide, le retourner
        if normalized in WorkflowStatus._value2member_map_:
            return normalized
        
        return normalized
    
    @classmethod
    def normalize_status_with_warning(cls, status: str) -> str:
        """
        Normalise un statut et logge un avertissement si un mapping a été appliqué.
        
        Args:
            status: Statut à normaliser
            
        Returns:
            str: Statut normalisé
        """
        if status in cls.STATUS_MAPPINGS:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Status normalisé: '{status}' -> '{cls.STATUS_MAPPINGS[status]}'"
            )
        return cls.normalize_status(status)
    
    # ==========================================================================
    # MÉTHODES DE VALIDATION
    # ==========================================================================
    
    @classmethod
    def validate_status(cls, status: str, allowed_statuses: Optional[Union[Set[str], List[str]]] = None) -> bool:
        """
        Valide un statut par rapport à une liste autorisée.
        
        Args:
            status: Statut à valider
            allowed_statuses: Ensemble ou liste des statuts autorisés
            
        Returns:
            bool: True si le statut est valide
        """
        normalized = cls.normalize_status(status)
        
        if allowed_statuses is None:
            # Valider par rapport à toutes les enumérations
            all_statuses = set(TaskStatus._value2member_map_.keys())
            all_statuses.update(AgentStatus._value2member_map_.keys())
            all_statuses.update(WorkflowStatus._value2member_map_.keys())
            return normalized in all_statuses
        
        if isinstance(allowed_statuses, list):
            allowed_statuses = set(allowed_statuses)
        
        return normalized in {s.lower() for s in allowed_statuses}
    
    @classmethod
    def is_terminal(cls, status: str) -> bool:
        """
        Vérifie si un statut est terminal.
        
        Args:
            status: Statut à vérifier
            
        Returns:
            bool: True si le statut est terminal
        """
        normalized = cls.normalize_status(status)
        return normalized in cls.TERMINAL_STATUSES
    
    @classmethod
    def is_failure(cls, status: str) -> bool:
        """
        Vérifie si un statut indique un échec.
        
        Args:
            status: Statut à vérifier
            
        Returns:
            bool: True si le statut est un échec
        """
        normalized = cls.normalize_status(status)
        return normalized in cls.FAILURE_STATUSES
    
    @classmethod
    def is_success(cls, status: str) -> bool:
        """
        Vérifie si un statut indique un succès.
        
        Args:
            status: Statut à vérifier
            
        Returns:
            bool: True si le statut est un succès
        """
        normalized = cls.normalize_status(status)
        return normalized == TaskStatus.SUCCESS.value
    
    @classmethod
    def needs_human_intervention(cls, status: str) -> bool:
        """
        Vérifie si un statut nécessite une intervention humaine.
        
        Args:
            status: Statut à vérifier
            
        Returns:
            bool: True si une intervention humaine est nécessaire
        """
        normalized = cls.normalize_status(status)
        return normalized in cls.HUMAN_STATUSES
    
    # ==========================================================================
    # MÉTHODES DE CONVERSION
    # ==========================================================================
    
    @classmethod
    def to_task_status(cls, status: str) -> Optional[TaskStatus]:
        """
        Convertit un statut en TaskStatus enum.
        
        Args:
            status: Statut à convertir
            
        Returns:
            Optional[TaskStatus]: TaskStatus correspondant ou None
        """
        normalized = cls.normalize_status(status)
        try:
            return TaskStatus(normalized)
        except ValueError:
            return None
    
    @classmethod
    def to_agent_status(cls, status: str) -> Optional[AgentStatus]:
        """
        Convertit un statut en AgentStatus enum.
        
        Args:
            status: Statut à convertir
            
        Returns:
            Optional[AgentStatus]: AgentStatus correspondant ou None
        """
        normalized = cls.normalize_status(status)
        try:
            return AgentStatus(normalized)
        except ValueError:
            return None
    
    @classmethod
    def to_workflow_status(cls, status: str) -> Optional[WorkflowStatus]:
        """
        Convertit un statut en WorkflowStatus enum.
        
        Args:
            status: Statut à convertir
            
        Returns:
            Optional[WorkflowStatus]: WorkflowStatus correspondant ou None
        """
        normalized = cls.normalize_status(status)
        try:
            return WorkflowStatus(normalized)
        except ValueError:
            return None
    
    # ==========================================================================
    # MÉTHODES DE STATISTIQUES
    # ==========================================================================
    
    def record_usage(self, status: str, context: Optional[str] = None) -> None:
        """
        Enregistre l'utilisation d'un statut pour les métriques.
        
        Args:
            status: Statut utilisé
            context: Contexte d'utilisation (optionnel)
        """
        normalized = self.normalize_status(status)
        self._metrics["by_status"][normalized] = self._metrics["by_status"].get(normalized, 0) + 1
        
        if context:
            self._normalization_history.append({
                "status": normalized,
                "context": context,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Retourne les métriques d'utilisation des statuts.
        
        Returns:
            Dict[str, Any]: Métriques
        """
        total_uses = sum(self._metrics["by_status"].values())
        return {
            **self._metrics,
            "total_uses": total_uses,
            "history_size": len(self._normalization_history),
            "most_used": self._get_most_used(),
        }
    
    def _get_most_used(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retourne les statuts les plus utilisés."""
        sorted_statuses = sorted(
            self._metrics["by_status"].items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [
            {"status": status, "count": count}
            for status, count in sorted_statuses[:limit]
            if count > 0
        ]


# ==============================================================================
# INSTANCE GLOBALE
# ==============================================================================

# Instance unique pour une utilisation cohérente dans tout le pipeline
status_manager = StatusManager()


# ==============================================================================
# FONCTIONS DE CONVENANCE
# ==============================================================================

def normalize_status(status: Union[str, Enum]) -> str:
    """Fonction de convenance pour normaliser un statut."""
    return StatusManager.normalize_status(status)


def validate_status(status: str, allowed_statuses: Optional[Union[Set[str], List[str]]] = None) -> bool:
    """Fonction de convenance pour valider un statut."""
    return StatusManager.validate_status(status, allowed_statuses)


def is_terminal(status: str) -> bool:
    """Fonction de convenance pour vérifier si un statut est terminal."""
    return StatusManager.is_terminal(status)


def is_failure(status: str) -> bool:
    """Fonction de convenance pour vérifier si un statut est un échec."""
    return StatusManager.is_failure(status)


def is_success(status: str) -> bool:
    """Fonction de convenance pour vérifier si un statut est un succès."""
    return StatusManager.is_success(status)


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Contract Dev Pipeline 2.0 - Status Manager")
    print("=" * 60)
    
    # Test de normalisation
    print("\n📋 Test de normalisation:")
    test_statuses = [
        "SUCCESS", "SUCCESS", "FAILED", "CIRCUIT_OPEN", "PENDING",
        "RUNNING", "WAITING_HUMAN_VALIDATION", "circuit_broken",
        "success", "failed", "COMPLETED", "IDLE"
    ]
    
    for status in test_statuses:
        normalized = StatusManager.normalize_status(status)
        print(f"  '{status}' -> '{normalized}'")
    
    # Test de validation
    print("\n📋 Test de validation:")
    print(f"  is_success('SUCCESS'): {StatusManager.is_success('SUCCESS')}")
    print(f"  is_success('failed'): {StatusManager.is_success('failed')}")
    print(f"  is_terminal('SUCCESS'): {StatusManager.is_terminal('SUCCESS')}")
    print(f"  is_terminal('RUNNING'): {StatusManager.is_terminal('RUNNING')}")
    print(f"  is_failure('FAILED'): {StatusManager.is_failure('FAILED')}")
    print(f"  is_failure('CIRCUIT_BROKEN'): {StatusManager.is_failure('CIRCUIT_BROKEN')}")
    print(f"  needs_human_intervention('WAITING_HUMAN_VALIDATION'): {StatusManager.needs_human_intervention('WAITING_HUMAN_VALIDATION')}")
    
    # Test de conversion
    print("\n📋 Test de conversion:")
    task_status = StatusManager.to_task_status("SUCCESS")
    print(f"  to_task_status('SUCCESS'): {task_status}")
    agent_status = StatusManager.to_agent_status("IDLE")
    print(f"  to_agent_status('IDLE'): {agent_status}")
    workflow_status = StatusManager.to_workflow_status("PENDING")
    print(f"  to_workflow_status('PENDING'): {workflow_status}")
    
    # Test des fonctions de convenance
    print("\n📋 Test des fonctions de convenance:")
    print(f"  normalize_status('CIRCUIT_OPEN'): {normalize_status('CIRCUIT_OPEN')}")
    print(f"  validate_status('success'): {validate_status('success')}")
    print(f"  is_terminal('COMPLETED'): {is_terminal('COMPLETED')}")
    
    # Test des métriques
    print("\n📋 Test des métriques:")
    sm = StatusManager()
    sm.record_usage("SUCCESS", "test_1")
    sm.record_usage("FAILED", "test_2")
    sm.record_usage("SUCCESS", "test_3")
    sm.record_usage("CIRCUIT_BROKEN", "test_4")
    
    metrics = sm.get_metrics()
    print(f"  Total uses: {metrics['total_uses']}")
    print(f"  Most used: {metrics['most_used']}")
    
    print("\n✅ Tests terminés.")