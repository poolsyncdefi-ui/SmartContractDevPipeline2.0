# src/orchestration/circuit_breaker.py
from typing import Dict
from src.config.settings import settings

class AutoDebugCircuitBreaker:
    """Disjoncteur limitant les tentatives d'auto-correction."""
    
    def __init__(self, max_retries: int = None):
        self.max_retries = max_retries or settings.max_auto_debug_retries
        self._failures: Dict[str, int] = {}

    def can_retry(self, task_id: str) -> bool:
        """Vérifie si une nouvelle tentative est autorisée."""
        return self._failures.get(task_id, 0) < self.max_retries

    def record_failure(self, task_id: str, error_log: str) -> int:
        """Enregistre un échec et retourne le nombre de tentatives."""
        current = self._failures.get(task_id, 0) + 1
        self._failures[task_id] = current
        return current

    def reset(self, task_id: str) -> None:
        """Réinitialise le compteur d'échecs."""
        if task_id in self._failures:
            del self._failures[task_id]

    def get_status(self, task_id: str) -> str:
        """Retourne le statut du circuit breaker."""
        if task_id not in self._failures:
            return "CLOSED"
        if self._failures[task_id] >= self.max_retries:
            return "OPEN"
        return "HALF_OPEN"