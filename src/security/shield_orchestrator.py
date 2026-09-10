# src/security/shield_orchestrator.py
"""
Shield Orchestrator - Orchestrateur de sécurité pour le pipeline.

Rôle Fonctionnel :
    Ce module implémente l'orchestrateur de sécurité (Shield) qui coordonne
    l'ensemble des analyses de sécurité appliquées aux smart contracts :
    - Analyse statique (Slither)
    - Vérification formelle (Halmos)
    - Détection de vulnérabilités
    - Scoring de sécurité
    - Génération de rapports d'audit

    L'orchestrateur utilise un logger structuré pour tracer toutes les
    exécutions et expose une interface asynchrone pour l'intégration
    dans le pipeline principal.

Architecture :
    ShieldOrchestrator
        ├── SecurityAnalyzer (analyse statique)
        ├── FormalVerifier (vérification formelle)
        ├── VulnerabilityScanner (détection)
        └── SecurityScorer (scoring)

Dépendances :
    - src.core.models (TaskStatus, LogLevel, etc.)
    - src.core.exceptions (SecurityError, etc.)
    - src.utils.structured_logger (StructuredLogger)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# IMPORTS INTERNES (chemins harmonisés)
# =============================================================================
from src.core.models import (
    TaskStatus,
    LogLevel,
    SecuritySeverity,
    SecurityFinding,
    SecurityReport,
)
from src.core.exceptions import (
    SecurityError,
    ShieldOrchestratorError,
    AnalysisError,
    VerificationError,
)
from src.utils.structured_logger import StructuredLogger


# =============================================================================
# LOGGER STRUCTURÉ
# =============================================================================
logger = StructuredLogger(__name__)


# =============================================================================
# ENUMS
# =============================================================================
class ShieldState(str, Enum):
    """États possibles de l'orchestrateur Shield."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    ANALYZING = "analyzing"
    VERIFYING = "verifying"
    SCANNING = "scanning"
    SCORING = "scoring"
    COMPLETED = "completed"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    CANCELLED = "cancelled"


class AnalysisType(str, Enum):
    """Types d'analyses de sécurité."""
    STATIC = "static"           # Slither
    FORMAL = "formal"           # Halmos
    SYMBOLIC = "symbolic"       # Symbolic execution
    FUZZING = "fuzzing"         # Fuzzing
    MANUAL = "manual"           # Revue manuelle
    DEPENDENCY = "dependency"   # Analyse des dépendances


class SeverityLevel(str, Enum):
    """Niveaux de sévérité des vulnérabilités."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    UNKNOWN = "unknown"


# =============================================================================
# MODÈLES PYDANTIC
# =============================================================================
class ShieldConfig(BaseModel):
    """Configuration de l'orchestrateur Shield."""
    enable_static_analysis: bool = Field(default=True)
    enable_formal_verification: bool = Field(default=True)
    enable_fuzzing: bool = Field(default=False)
    enable_dependency_check: bool = Field(default=True)

    slither_timeout: int = Field(default=60, ge=1)
    halmos_timeout: int = Field(default=300, ge=1)
    fuzzing_timeout: int = Field(default=120, ge=1)

    max_retries: int = Field(default=3, ge=0)
    retry_delay: float = Field(default=1.0, ge=0.0)
    circuit_breaker_threshold: int = Field(default=5, ge=1)

    min_security_score: float = Field(default=80.0, ge=0.0, le=100.0)
    fail_on_critical: bool = Field(default=True)
    fail_on_high: bool = Field(default=False)

    output_dir: str = Field(default="./security_reports")
    generate_json_report: bool = Field(default=True)
    generate_markdown_report: bool = Field(default=True)

    @field_validator("output_dir")
    @classmethod
    def validate_output_dir(cls, v: str) -> str:
        """Valide le répertoire de sortie."""
        if not v or not v.strip():
            raise ValueError("output_dir cannot be empty")
        return v.strip()


class ShieldResult(BaseModel):
    """Résultat d'une exécution de l'orchestrateur Shield."""
    task_id: str
    status: TaskStatus
    security_score: float = Field(default=0.0, ge=0.0, le=100.0)
    findings: List[SecurityFinding] = Field(default_factory=list)
    report: Optional[SecurityReport] = None
    error: Optional[str] = None
    duration: float = Field(default=0.0, ge=0.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Config:
        arbitrary_types_allowed = True


# =============================================================================
# ORCHESTRATEUR SHIELD
# =============================================================================
class ShieldOrchestrator:
    """
    Orchestrateur de sécurité pour les smart contracts.

    Coordonne les différentes analyses de sécurité, agrège les résultats,
    calcule un score de sécurité et génère des rapports.

    Attributes:
        config (ShieldConfig): Configuration de l'orchestrateur.
        state (ShieldState): État actuel de l'orchestrateur.
        _cancelled (bool): Flag d'annulation.
        _findings (List[SecurityFinding]): Liste des vulnérabilités trouvées.
        _stats (Dict[str, Any]): Statistiques d'exécution.
    """

    def __init__(self, config: Optional[ShieldConfig] = None):
        """
        Initialise l'orchestrateur Shield.

        Args:
            config: Configuration optionnelle. Si None, utilise les valeurs par défaut.
        """
        self.config = config or ShieldConfig()
        self.state = ShieldState.IDLE
        self._cancelled = False
        self._findings: List[SecurityFinding] = []
        self._stats: Dict[str, Any] = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_findings": 0,
            "critical_findings": 0,
            "high_findings": 0,
            "medium_findings": 0,
            "low_findings": 0,
            "started_at": None,
            "last_run_at": None,
        }
        self._lock = asyncio.Lock()
        self._circuit_breaker_failures = 0
        self._circuit_breaker_open = False

        logger.info(
            "ShieldOrchestrator initialized",
            event="shield_init",
            config=self.config.model_dump(),
        )

    # =========================================================================
    # PROPRIÉTÉS
    # =========================================================================
    @property
    def is_cancelled(self) -> bool:
        """Indique si l'orchestrateur a été annulé."""
        return self._cancelled

    @property
    def is_circuit_broken(self) -> bool:
        """Indique si le circuit breaker est ouvert."""
        return self._circuit_breaker_open

    # =========================================================================
    # MÉTHODE PRINCIPALE
    # =========================================================================
    async def run(
        self,
        task_id: str,
        contract_path: Union[str, Path],
        contract_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ShieldResult:
        """
        Exécute l'orchestration complète de sécurité.

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin vers le contrat à analyser.
            contract_name: Nom du contrat (optionnel).
            context: Contexte additionnel (optionnel).

        Returns:
            ShieldResult: Résultat de l'analyse.

        Raises:
            ShieldOrchestratorError: Si une erreur critique survient.
        """
        start_time = time.monotonic()
        context = context or {}

        async with self._lock:
            if self._circuit_breaker_open:
                logger.warning(
                    "Shield circuit breaker is open, rejecting task",
                    event="shield_circuit_broken",
                    task_id=task_id,
                )
                return ShieldResult(
                    task_id=task_id,
                    status=TaskStatus.CIRCUIT_BROKEN,
                    error="Circuit breaker is open",
                    duration=time.monotonic() - start_time,
                )

            self._stats["total_runs"] += 1
            self._stats["started_at"] = datetime.now(timezone.utc)
            self._cancelled = False
            self._findings = []

            logger.info(
                "Shield orchestration started",
                event="shield_start",
                task_id=task_id,
                contract_path=str(contract_path),
                contract_name=contract_name,
            )

            try:
                # Étape 1 : Initialisation
                self.state = ShieldState.INITIALIZING
                await self._initialize(task_id, contract_path, contract_name)

                # Étape 2 : Analyse statique
                if self.config.enable_static_analysis and not self._cancelled:
                    self.state = ShieldState.ANALYZING
                    await self._run_static_analysis(task_id, contract_path)

                # Étape 3 : Vérification formelle
                if self.config.enable_formal_verification and not self._cancelled:
                    self.state = ShieldState.VERIFYING
                    await self._run_formal_verification(task_id, contract_path)

                # Étape 4 : Détection de vulnérabilités
                if self.config.enable_fuzzing and not self._cancelled:
                    self.state = ShieldState.SCANNING
                    await self._run_fuzzing(task_id, contract_path)

                # Étape 5 : Analyse des dépendances
                if self.config.enable_dependency_check and not self._cancelled:
                    self.state = ShieldState.SCANNING
                    await self._run_dependency_check(task_id, contract_path)

                # Vérification d'annulation
                if self._cancelled:
                    logger.warning(
                        "Shield orchestration cancelled",
                        event="shield_cancelled",
                        task_id=task_id,
                    )
                    self.state = ShieldState.CANCELLED
                    return ShieldResult(
                        task_id=task_id,
                        status=TaskStatus.CANCELLED,
                        error="Cancelled by user",
                        duration=time.monotonic() - start_time,
                    )

                # Étape 6 : Scoring
                self.state = ShieldState.SCORING
                security_score = await self._calculate_security_score(task_id)

                # Étape 7 : Génération du rapport
                report = await self._generate_report(
                    task_id, contract_path, contract_name, security_score
                )

                # Étape 8 : Évaluation du succès
                status = self._evaluate_status(security_score)

                self.state = ShieldState.COMPLETED
                self._stats["successful_runs"] += 1
                self._stats["last_run_at"] = datetime.now(timezone.utc)
                self._circuit_breaker_failures = 0

                duration = time.monotonic() - start_time

                logger.info(
                    "Shield orchestration completed",
                    event="shield_completed",
                    task_id=task_id,
                    status=status.value,
                    security_score=security_score,
                    findings_count=len(self._findings),
                    duration=duration,
                )

                return ShieldResult(
                    task_id=task_id,
                    status=status,
                    security_score=security_score,
                    findings=self._findings,
                    report=report,
                    duration=duration,
                )

            except asyncio.CancelledError:
                logger.warning(
                    "Shield orchestration cancelled (asyncio)",
                    event="shield_asyncio_cancelled",
                    task_id=task_id,
                )
                self.state = ShieldState.CANCELLED
                raise

            except Exception as e:
                self.state = ShieldState.FAILED
                self._stats["failed_runs"] += 1
                self._stats["last_run_at"] = datetime.now(timezone.utc)
                self._circuit_breaker_failures += 1

                if self._circuit_breaker_failures >= self.config.circuit_breaker_threshold:
                    self._circuit_breaker_open = True
                    logger.error(
                        "Shield circuit breaker opened",
                        event="shield_circuit_open",
                        task_id=task_id,
                        failures=self._circuit_breaker_failures,
                    )

                logger.error(
                    "Shield orchestration failed",
                    event="shield_failed",
                    task_id=task_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    duration=time.monotonic() - start_time,
                )

                return ShieldResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=str(e),
                    duration=time.monotonic() - start_time,
                )

    # =========================================================================
    # ÉTAPES D'ORCHESTRATION
    # =========================================================================
    async def _initialize(
        self,
        task_id: str,
        contract_path: Union[str, Path],
        contract_name: Optional[str],
    ) -> None:
        """
        Initialise l'orchestration (vérifications préliminaires).

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
            contract_name: Nom du contrat.

        Raises:
            ShieldOrchestratorError: Si l'initialisation échoue.
        """
        path = Path(contract_path) if isinstance(contract_path, str) else contract_path

        if not path.exists():
            raise ShieldOrchestratorError(
                f"Contract path does not exist: {path}",
                details={"task_id": task_id, "path": str(path)},
            )

        if not path.is_file():
            raise ShieldOrchestratorError(
                f"Contract path is not a file: {path}",
                details={"task_id": task_id, "path": str(path)},
            )

        # Créer le répertoire de sortie
        output_dir = Path(self.config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(
            "Shield initialization completed",
            event="shield_init_done",
            task_id=task_id,
            contract_path=str(path),
            contract_name=contract_name,
        )

    async def _run_static_analysis(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """
        Exécute l'analyse statique (Slither).

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
        """
        logger.info(
            "Starting static analysis",
            event="shield_static_start",
            task_id=task_id,
            timeout=self.config.slither_timeout,
        )

        try:
            # Simulation de l'exécution Slither
            # En production, remplacer par l'appel réel à Slither
            await self._execute_with_retry(
                self._simulate_slither,
                task_id,
                contract_path,
                retries=self.config.max_retries,
                delay=self.config.retry_delay,
            )

            logger.info(
                "Static analysis completed",
                event="shield_static_done",
                task_id=task_id,
                findings_count=len(self._findings),
            )

        except Exception as e:
            logger.error(
                "Static analysis failed",
                event="shield_static_failed",
                task_id=task_id,
                error=str(e),
            )
            raise AnalysisError(
                f"Static analysis failed: {e}",
                details={"task_id": task_id, "contract_path": str(contract_path)},
            ) from e

    async def _run_formal_verification(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """
        Exécute la vérification formelle (Halmos).

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
        """
        logger.info(
            "Starting formal verification",
            event="shield_formal_start",
            task_id=task_id,
            timeout=self.config.halmos_timeout,
        )

        try:
            await self._execute_with_retry(
                self._simulate_halmos,
                task_id,
                contract_path,
                retries=self.config.max_retries,
                delay=self.config.retry_delay,
            )

            logger.info(
                "Formal verification completed",
                event="shield_formal_done",
                task_id=task_id,
            )

        except Exception as e:
            logger.error(
                "Formal verification failed",
                event="shield_formal_failed",
                task_id=task_id,
                error=str(e),
            )
            raise VerificationError(
                f"Formal verification failed: {e}",
                details={"task_id": task_id, "contract_path": str(contract_path)},
            ) from e

    async def _run_fuzzing(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """
        Exécute le fuzzing.

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
        """
        logger.info(
            "Starting fuzzing",
            event="shield_fuzzing_start",
            task_id=task_id,
            timeout=self.config.fuzzing_timeout,
        )

        try:
            await self._execute_with_retry(
                self._simulate_fuzzing,
                task_id,
                contract_path,
                retries=self.config.max_retries,
                delay=self.config.retry_delay,
            )

            logger.info(
                "Fuzzing completed",
                event="shield_fuzzing_done",
                task_id=task_id,
            )

        except Exception as e:
            logger.error(
                "Fuzzing failed",
                event="shield_fuzzing_failed",
                task_id=task_id,
                error=str(e),
            )
            raise AnalysisError(
                f"Fuzzing failed: {e}",
                details={"task_id": task_id, "contract_path": str(contract_path)},
            ) from e

    async def _run_dependency_check(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """
        Exécute l'analyse des dépendances.

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
        """
        logger.info(
            "Starting dependency check",
            event="shield_dependency_start",
            task_id=task_id,
        )

        try:
            await self._simulate_dependency_check(task_id, contract_path)

            logger.info(
                "Dependency check completed",
                event="shield_dependency_done",
                task_id=task_id,
            )

        except Exception as e:
            logger.error(
                "Dependency check failed",
                event="shield_dependency_failed",
                task_id=task_id,
                error=str(e),
            )
            # Non bloquant
            pass

    # =========================================================================
    # EXÉCUTION AVEC RETRY ET ANNULATION
    # =========================================================================
    async def _execute_with_retry(
        self,
        func: Any,
        task_id: str,
        contract_path: Union[str, Path],
        retries: int = 3,
        delay: float = 1.0,
    ) -> Any:
        """
        Exécute une fonction avec retry et gestion d'annulation.

        Args:
            func: Fonction à exécuter.
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
            retries: Nombre de tentatives.
            delay: Délai initial entre les tentatives.

        Returns:
            Any: Résultat de la fonction.

        Raises:
            Exception: Si toutes les tentatives échouent.
        """
        last_exception: Optional[Exception] = None

        for attempt in range(retries + 1):
            if self._cancelled:
                logger.info(
                    "Execution cancelled before attempt",
                    event="shield_exec_cancelled",
                    task_id=task_id,
                    attempt=attempt,
                )
                raise asyncio.CancelledError("Cancelled by user")

            try:
                return await func(task_id, contract_path)

            except asyncio.CancelledError:
                raise

            except Exception as e:
                last_exception = e
                logger.warning(
                    "Attempt failed",
                    event="shield_attempt_failed",
                    task_id=task_id,
                    attempt=attempt + 1,
                    max_attempts=retries + 1,
                    error=str(e),
                )

                if attempt < retries:
                    # Backoff exponentiel avec vérification d'annulation
                    wait_time = delay * (2 ** attempt)
                    await self._interruptible_sleep(wait_time, task_id)

        if last_exception:
            raise last_exception
        raise ShieldOrchestratorError("Execution failed without exception")

    async def _interruptible_sleep(self, duration: float, task_id: str) -> None:
        """
        Sleep interruptible qui vérifie régulièrement le flag d'annulation.

        Args:
            duration: Durée totale du sleep en secondes.
            task_id: Identifiant de la tâche (pour logging).
        """
        interval = 0.5
        elapsed = 0.0

        while elapsed < duration:
            if self._cancelled:
                logger.info(
                    "Sleep interrupted by cancellation",
                    event="shield_sleep_cancelled",
                    task_id=task_id,
                    elapsed=elapsed,
                    duration=duration,
                )
                raise asyncio.CancelledError("Cancelled by user")

            sleep_time = min(interval, duration - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

    # =========================================================================
    # SIMULATIONS (à remplacer par les vraies implémentations)
    # =========================================================================
    async def _simulate_slither(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """Simule l'exécution de Slither."""
        await asyncio.sleep(0.1)

        # Exemple de findings simulés
        self._add_finding(
            task_id=task_id,
            severity=SeverityLevel.MEDIUM,
            title="Reentrancy vulnerability",
            description="Potential reentrancy in withdraw function",
            location=str(contract_path),
            line=42,
            tool="slither",
        )

    async def _simulate_halmos(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """Simule l'exécution de Halmos."""
        await asyncio.sleep(0.2)

    async def _simulate_fuzzing(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """Simule le fuzzing."""
        await asyncio.sleep(0.15)

    async def _simulate_dependency_check(
        self,
        task_id: str,
        contract_path: Union[str, Path],
    ) -> None:
        """Simule l'analyse des dépendances."""
        await asyncio.sleep(0.05)

    # =========================================================================
    # GESTION DES FINDINGS
    # =========================================================================
    def _add_finding(
        self,
        task_id: str,
        severity: SeverityLevel,
        title: str,
        description: str,
        location: str,
        line: Optional[int] = None,
        tool: str = "unknown",
        cwe_id: Optional[str] = None,
        recommendation: Optional[str] = None,
    ) -> None:
        """
        Ajoute une vulnérabilité à la liste.

        Args:
            task_id: Identifiant de la tâche.
            severity: Sévérité de la vulnérabilité.
            title: Titre court.
            description: Description détaillée.
            location: Emplacement dans le code.
            line: Numéro de ligne (optionnel).
            tool: Outil ayant détecté la vulnérabilité.
            cwe_id: Identifiant CWE (optionnel).
            recommendation: Recommandation de correction (optionnelle).
        """
        finding = SecurityFinding(
            id=self._generate_finding_id(task_id, title, location, line),
            task_id=task_id,
            severity=severity.value,
            title=title,
            description=description,
            location=location,
            line=line,
            tool=tool,
            cwe_id=cwe_id,
            recommendation=recommendation,
            detected_at=datetime.now(timezone.utc),
        )

        self._findings.append(finding)
        self._stats["total_findings"] += 1

        severity_key = f"{severity.value}_findings"
        if severity_key in self._stats:
            self._stats[severity_key] += 1

        logger.debug(
            "Finding added",
            event="shield_finding_added",
            task_id=task_id,
            severity=severity.value,
            title=title,
            tool=tool,
        )

    def _generate_finding_id(
        self,
        task_id: str,
        title: str,
        location: str,
        line: Optional[int],
    ) -> str:
        """Génère un identifiant unique pour un finding."""
        content = f"{task_id}:{title}:{location}:{line}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    # =========================================================================
    # SCORING
    # =========================================================================
    async def _calculate_security_score(self, task_id: str) -> float:
        """
        Calcule le score de sécurité basé sur les findings.

        Args:
            task_id: Identifiant de la tâche.

        Returns:
            float: Score entre 0 et 100.
        """
        if not self._findings:
            logger.info(
                "No findings, perfect security score",
                event="shield_score_perfect",
                task_id=task_id,
            )
            return 100.0

        # Pondération par sévérité
        weights = {
            SeverityLevel.CRITICAL.value: 25.0,
            SeverityLevel.HIGH.value: 15.0,
            SeverityLevel.MEDIUM.value: 8.0,
            SeverityLevel.LOW.value: 3.0,
            SeverityLevel.INFO.value: 1.0,
            SeverityLevel.UNKNOWN.value: 2.0,
        }

        total_penalty = 0.0
        for finding in self._findings:
            total_penalty += weights.get(finding.severity, 2.0)

        # Score = 100 - pénalité, borné à 0
        score = max(0.0, 100.0 - total_penalty)

        logger.info(
            "Security score calculated",
            event="shield_score_calculated",
            task_id=task_id,
            score=score,
            findings_count=len(self._findings),
            total_penalty=total_penalty,
        )

        return round(score, 2)

    def _evaluate_status(self, security_score: float) -> TaskStatus:
        """
        Évalue le statut final basé sur le score et les findings.

        Args:
            security_score: Score de sécurité calculé.

        Returns:
            TaskStatus: Statut final.
        """
        # Vérifier les findings critiques
        if self.config.fail_on_critical:
            critical_findings = [
                f for f in self._findings if f.severity == SeverityLevel.CRITICAL.value
            ]
            if critical_findings:
                logger.warning(
                    "Critical findings detected, marking as failed",
                    event="shield_critical_failed",
                    critical_count=len(critical_findings),
                )
                return TaskStatus.FAILED

        if self.config.fail_on_high:
            high_findings = [
                f for f in self._findings if f.severity == SeverityLevel.HIGH.value
            ]
            if high_findings:
                logger.warning(
                    "High findings detected, marking as failed",
                    event="shield_high_failed",
                    high_count=len(high_findings),
                )
                return TaskStatus.FAILED

        # Vérifier le score minimum
        if security_score < self.config.min_security_score:
            logger.warning(
                "Security score below threshold",
                event="shield_score_below_threshold",
                score=security_score,
                threshold=self.config.min_security_score,
            )
            return TaskStatus.FAILED

        return TaskStatus.SUCCESS

    # =========================================================================
    # GÉNÉRATION DE RAPPORT
    # =========================================================================
    async def _generate_report(
        self,
        task_id: str,
        contract_path: Union[str, Path],
        contract_name: Optional[str],
        security_score: float,
    ) -> SecurityReport:
        """
        Génère le rapport de sécurité.

        Args:
            task_id: Identifiant de la tâche.
            contract_path: Chemin du contrat.
            contract_name: Nom du contrat.
            security_score: Score de sécurité.

        Returns:
            SecurityReport: Rapport généré.
        """
        report = SecurityReport(
            task_id=task_id,
            contract_path=str(contract_path),
            contract_name=contract_name or Path(contract_path).stem,
            security_score=security_score,
            findings=self._findings,
            generated_at=datetime.now(timezone.utc),
            metadata={
                "orchestrator": "ShieldOrchestrator",
                "config": self.config.model_dump(),
                "stats": self._stats,
            },
        )

        # Sauvegarder les rapports si configuré
        output_dir = Path(self.config.output_dir)

        if self.config.generate_json_report:
            json_path = output_dir / f"{task_id}_security_report.json"
            await self._save_json_report(report, json_path)

        if self.config.generate_markdown_report:
            md_path = output_dir / f"{task_id}_security_report.md"
            await self._save_markdown_report(report, md_path)

        logger.info(
            "Security report generated",
            event="shield_report_generated",
            task_id=task_id,
            output_dir=str(output_dir),
            score=security_score,
        )

        return report

    async def _save_json_report(self, report: SecurityReport, path: Path) -> None:
        """Sauvegarde le rapport au format JSON."""
        try:
            data = report.model_dump(mode="json")
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            logger.debug(
                "JSON report saved",
                event="shield_json_saved",
                path=str(path),
            )
        except Exception as e:
            logger.error(
                "Failed to save JSON report",
                event="shield_json_save_failed",
                path=str(path),
                error=str(e),
            )

    async def _save_markdown_report(self, report: SecurityReport, path: Path) -> None:
        """Sauvegarde le rapport au format Markdown."""
        try:
            lines = [
                f"# Security Report - {report.contract_name}",
                "",
                f"**Task ID:** {report.task_id}",
                f"**Contract:** {report.contract_path}",
                f"**Security Score:** {report.security_score}/100",
                f"**Generated:** {report.generated_at.isoformat()}",
                "",
                "## Findings",
                "",
            ]

            if not report.findings:
                lines.append("No vulnerabilities found. ✅")
            else:
                for i, finding in enumerate(report.findings, 1):
                    lines.extend([
                        f"### {i}. {finding.title}",
                        "",
                        f"- **Severity:** {finding.severity}",
                        f"- **Location:** {finding.location}",
                        f"- **Line:** {finding.line or 'N/A'}",
                        f"- **Tool:** {finding.tool}",
                        f"- **CWE:** {finding.cwe_id or 'N/A'}",
                        "",
                        f"{finding.description}",
                        "",
                    ])
                    if finding.recommendation:
                        lines.extend([
                            f"**Recommendation:** {finding.recommendation}",
                            "",
                        ])

            path.write_text("\n".join(lines))
            logger.debug(
                "Markdown report saved",
                event="shield_markdown_saved",
                path=str(path),
            )
        except Exception as e:
            logger.error(
                "Failed to save Markdown report",
                event="shield_markdown_save_failed",
                path=str(path),
                error=str(e),
            )

    # =========================================================================
    # ANNULATION
    # =========================================================================
    def cancel(self) -> None:
        """
        Annule l'orchestration en cours.

        Le flag est vérifié régulièrement dans les boucles d'exécution
        et les sleeps, permettant une sortie rapide.
        """
        self._cancelled = True
        logger.info(
            "Shield orchestration cancellation requested",
            event="shield_cancel_requested",
            state=self.state.value,
        )

    async def cancel_async(self) -> None:
        """Version asynchrone de l'annulation."""
        self.cancel()

    # =========================================================================
    # STATISTIQUES
    # =========================================================================
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'orchestrateur.

        Returns:
            Dict: Statistiques d'exécution.
        """
        return {
            **self._stats,
            "state": self.state.value,
            "circuit_breaker_open": self._circuit_breaker_open,
            "circuit_breaker_failures": self._circuit_breaker_failures,
            "current_findings": len(self._findings),
        }

    def reset_circuit_breaker(self) -> None:
        """Réinitialise le circuit breaker."""
        self._circuit_breaker_open = False
        self._circuit_breaker_failures = 0
        logger.info(
            "Circuit breaker reset",
            event="shield_circuit_reset",
        )

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self._stats = {
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "total_findings": 0,
            "critical_findings": 0,
            "high_findings": 0,
            "medium_findings": 0,
            "low_findings": 0,
            "started_at": None,
            "last_run_at": None,
        }
        logger.info("Stats reset", event="shield_stats_reset")

    # =========================================================================
    # REPRÉSENTATION
    # =========================================================================
    def __repr__(self) -> str:
        return (
            f"<ShieldOrchestrator(state={self.state.value}, "
            f"findings={len(self._findings)}, "
            f"circuit_broken={self._circuit_breaker_open})>"
        )

    def __str__(self) -> str:
        return self.__repr__()


# =============================================================================
# FACTORY
# =============================================================================
def create_shield_orchestrator(
    config: Optional[ShieldConfig] = None,
) -> ShieldOrchestrator:
    """
    Crée une instance de ShieldOrchestrator.

    Args:
        config: Configuration optionnelle.

    Returns:
        ShieldOrchestrator: Instance configurée.
    """
    return ShieldOrchestrator(config=config)


# =============================================================================
# POINT D'ENTRÉE POUR TESTS
# =============================================================================
if __name__ == "__main__":
    import sys

    async def main():
        """Point d'entrée pour test manuel."""
        print("=== ShieldOrchestrator Test ===\n")

        config = ShieldConfig(
            enable_static_analysis=True,
            enable_formal_verification=True,
            enable_fuzzing=False,
            min_security_score=80.0,
        )

        orchestrator = create_shield_orchestrator(config)

        # Créer un contrat de test
        test_contract = Path("./test_contract.sol")
        test_contract.write_text("// SPDX-License-Identifier: MIT\npragma solidity ^0.8.24;\n\ncontract Test {}\n")

        try:
            result = await orchestrator.run(
                task_id="test_task_001",
                contract_path=test_contract,
                contract_name="TestContract",
            )

            print(f"Status: {result.status.value}")
            print(f"Security Score: {result.security_score}")
            print(f"Findings: {len(result.findings)}")
            print(f"Duration: {result.duration:.2f}s")

            if result.error:
                print(f"Error: {result.error}")

            print("\nStats:")
            for key, value in orchestrator.get_stats().items():
                print(f"  {key}: {value}")

        finally:
            if test_contract.exists():
                test_contract.unlink()

        print("\n=== Test terminé ===")

    asyncio.run(main())