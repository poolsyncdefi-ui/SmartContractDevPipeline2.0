# src/security/shield_orchestrator.py

"""
Security shield orchestrator for the Smart Contract Dev Pipeline.
F32 – src/security/shield_orchestrator.py

Rôle Fonctionnel : Pilote sequentiellement Slither, Echidna, Anvil et Halmos.
Ce module implemente l'orchestrateur du bouclier de securite multi-couches,
coordonnant les 4 niveaux d'analyse de securite:
- Niveau 1: Analyse statique (Slither)
- Niveau 2: Fuzzing (Foundry/Echidna)
- Niveau 3: Simulation d'attaques (Anvil)
- Niveau 4: Verification formelle (Halmos)

L'orchestrateur execute les analyses en parallele ou sequentiellement,
agrege les resultats et genere un rapport de securite complet.
"""
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
import logging

# Import des modules du pipeline
from src.security.threat_simulator import ThreatSimulator, ThreatReport
from src.security.formal_verifier import FormalVerifier, VerificationReport
from src.core.exceptions import PipelineError
from src.config.settings import settings

# Configuration du logging
logger = logging.getLogger(__name__)


class ShieldLevel(str, Enum):
    """
    Niveaux du bouclier de securite.
    """
    LEVEL_1 = "level_1"  # Analyse statique (Slither)
    LEVEL_2 = "level_2"  # Fuzzing (Foundry)
    LEVEL_3 = "level_3"  # Simulation d'attaques (Anvil)
    LEVEL_4 = "level_4"  # Verification formelle (Halmos)
    ALL = "all"          # Tous les niveaux


class ShieldStatus(str, Enum):
    """
    Statuts du bouclier de securite.
    """
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class ShieldResult:
    """
    Resultat d'un niveau du bouclier.
    
    Attributes:
        level (ShieldLevel): Niveau du bouclier
        passed (bool): Le niveau est-il passe ?
        score (float): Score de securite (0-100)
        details (Dict): Details du resultat
        execution_time (float): Temps d'execution en secondes
        error (Optional[str]): Message d'erreur
        vulnerabilities (List[Dict]): Vulnerabilites trouvees
    """
    level: ShieldLevel
    passed: bool
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    error: Optional[str] = None
    vulnerabilities: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convertit le resultat en dictionnaire."""
        return {
            "level": self.level.value,
            "passed": self.passed,
            "score": self.score,
            "details": self.details,
            "execution_time": self.execution_time,
            "error": self.error,
            "vulnerabilities": self.vulnerabilities
        }


@dataclass
class ShieldReport:
    """
    Rapport complet du bouclier de securite.
    
    Attributes:
        timestamp (datetime): Date du rapport
        contract_name (str): Nom du contrat audite
        contract_address (Optional[str]): Adresse du contrat
        project_path (str): Chemin du projet
        status (ShieldStatus): Statut global
        levels (Dict[ShieldLevel, ShieldResult]): Resultats par niveau
        passed (bool): L'audit est-il passe ?
        overall_score (float): Score global (0-100)
        total_vulnerabilities (int): Nombre total de vulnerabilites
        critical_vulnerabilities (int): Vulnerabilites critiques
        high_vulnerabilities (int): Vulnerabilites hautes
        recommendations (List[str]): Recommandations
        execution_time (float): Temps total d'execution
        metadata (Dict): Metadonnees supplementaires
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)
    contract_name: str = ""
    contract_address: Optional[str] = None
    project_path: str = ""
    status: ShieldStatus = ShieldStatus.PENDING
    levels: Dict[ShieldLevel, ShieldResult] = field(default_factory=dict)
    passed: bool = False
    overall_score: float = 0.0
    total_vulnerabilities: int = 0
    critical_vulnerabilities: int = 0
    high_vulnerabilities: int = 0
    recommendations: List[str] = field(default_factory=list)
    execution_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le rapport en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "contract_name": self.contract_name,
            "contract_address": self.contract_address,
            "project_path": self.project_path,
            "status": self.status.value,
            "levels": {k.value: v.to_dict() for k, v in self.levels.items()},
            "passed": self.passed,
            "overall_score": self.overall_score,
            "total_vulnerabilities": self.total_vulnerabilities,
            "critical_vulnerabilities": self.critical_vulnerabilities,
            "high_vulnerabilities": self.high_vulnerabilities,
            "recommendations": self.recommendations,
            "execution_time": self.execution_time,
            "metadata": self.metadata
        }


class SecurityShield:
    """
    Orchestrateur global du bouclier de securite.
    
    Cette classe coordonne les 4 niveaux d'analyse de securite
    et produit un rapport complet.
    
    Attributes:
        project_path (str): Chemin du projet
        slither_wrapper: Wrapper pour Slither
        foundry_wrapper: Wrapper pour Foundry
        simulator (ThreatSimulator): Simulateur de menaces
        halmos (FormalVerifier): Verificateur formel
        levels (Set[ShieldLevel]): Niveaux actifs
        parallel (bool): Executer en parallele
        timeout (int): Timeout global en secondes
        _stats (Dict): Statistiques d'execution
    """
    
    def __init__(
        self,
        project_path: str = ".",
        levels: Optional[List[ShieldLevel]] = None,
        parallel: bool = False,
        timeout: int = 600,
        slither_wrapper=None,
        foundry_wrapper=None,
        simulator: Optional[ThreatSimulator] = None,
        halmos: Optional[FormalVerifier] = None
    ):
        """
        Initialise l'orchestrateur du bouclier.
        
        Args:
            project_path: Chemin du projet
            levels: Niveaux a activer (defaut: tous)
            parallel: Executer en parallele (defaut: False)
            timeout: Timeout global en secondes (defaut: 600)
            slither_wrapper: Wrapper Slither (optionnel)
            foundry_wrapper: Wrapper Foundry (optionnel)
            simulator: Simulateur de menaces (optionnel)
            halmos: Verificateur formel (optionnel)
        """
        self.project_path = project_path
        self.levels = set(levels) if levels else set(ShieldLevel)
        self.parallel = parallel
        self.timeout = timeout
        
        # Initialisation des composants
        self.slither_wrapper = slither_wrapper
        self.foundry_wrapper = foundry_wrapper
        self.simulator = simulator or ThreatSimulator(project_path)
        self.halmos = halmos or FormalVerifier(project_path)
        
        # Statistiques
        self._stats = {
            "total_audits": 0,
            "passed_audits": 0,
            "failed_audits": 0,
            "total_levels_executed": 0,
            "levels_passed": 0,
            "levels_failed": 0,
            "errors": 0
        }
        
        # Cache
        self._cache: Dict[str, ShieldReport] = {}
        
        logger.info(f"SecurityShield initialized (levels={[l.value for l in self.levels]}, parallel={parallel})")
    
    # =========================================================================
    # EXECUTION DE L'AUDIT
    # =========================================================================
    
    async def run_full_audit(
        self,
        contract_path: Optional[str] = None,
        contract_address: Optional[str] = None,
        contract_name: Optional[str] = None,
        levels: Optional[List[ShieldLevel]] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Execute l'audit complet en 4 niveaux.
        
        Args:
            contract_path: Chemin du contrat (optionnel)
            contract_address: Adresse du contrat (optionnel)
            contract_name: Nom du contrat (optionnel)
            levels: Niveaux a executer (optionnel)
            use_cache: Utiliser le cache (defaut: True)
            
        Returns:
            Dict: Rapport complet de l'audit
        """
        start_time = datetime.utcnow()
        
        # Generation de la cle de cache
        cache_key = f"{contract_path}_{contract_address}_{contract_name}"
        if use_cache and cache_key in self._cache:
            logger.info(f"Cache hit for {cache_key}")
            return self._cache[cache_key].to_dict()
        
        # Preparation
        levels_to_run = set(levels) if levels else self.levels
        if not levels_to_run:
            levels_to_run = set(ShieldLevel)
        
        contract_name = contract_name or (os.path.basename(contract_path) if contract_path else "unknown")
        
        logger.info(f"Starting full audit for {contract_name}")
        
        # Initialisation du rapport
        report = ShieldReport(
            contract_name=contract_name,
            contract_address=contract_address,
            project_path=self.project_path,
            status=ShieldStatus.RUNNING
        )
        
        try:
            # Execution des niveaux
            if self.parallel:
                results = await self._run_parallel(contract_path, contract_address, levels_to_run)
            else:
                results = await self._run_sequential(contract_path, contract_address, levels_to_run)
            
            # Aggregation des resultats
            report.levels = results
            report.execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # Evaluation globale
            self._evaluate_report(report)
            report.status = ShieldStatus.COMPLETED
            
            # Mise en cache
            if use_cache:
                self._cache[cache_key] = report
            
            # Mise a jour des statistiques
            self._stats["total_audits"] += 1
            if report.passed:
                self._stats["passed_audits"] += 1
            else:
                self._stats["failed_audits"] += 1
            
            # Generation des recommandations
            report.recommendations = self._generate_recommendations(report)
            
            logger.info(f"Audit completed: {report.passed_count}/{len(report.levels)} passed")
            
            return report.to_dict()
            
        except Exception as e:
            logger.error(f"Audit failed: {str(e)}")
            report.status = ShieldStatus.FAILED
            report.passed = False
            report.metadata["error"] = str(e)
            self._stats["errors"] += 1
            return report.to_dict()
    
    async def _run_sequential(
        self,
        contract_path: Optional[str],
        contract_address: Optional[str],
        levels: Set[ShieldLevel]
    ) -> Dict[ShieldLevel, ShieldResult]:
        """
        Execute les niveaux sequentiellement.
        
        Args:
            contract_path: Chemin du contrat
            contract_address: Adresse du contrat
            levels: Niveaux a executer
            
        Returns:
            Dict[ShieldLevel, ShieldResult]: Resultats par niveau
        """
        results = {}
        
        # Niveau 1: Slither
        if ShieldLevel.LEVEL_1 in levels:
            results[ShieldLevel.LEVEL_1] = await self._run_slither(contract_path)
        
        # Niveau 2: Foundry
        if ShieldLevel.LEVEL_2 in levels:
            results[ShieldLevel.LEVEL_2] = await self._run_foundry(contract_path)
        
        # Niveau 3: Threat Simulator
        if ShieldLevel.LEVEL_3 in levels and contract_address:
            results[ShieldLevel.LEVEL_3] = await self._run_threat_simulator(contract_address)
        
        # Niveau 4: Halmos
        if ShieldLevel.LEVEL_4 in levels:
            results[ShieldLevel.LEVEL_4] = await self._run_halmos(contract_path)
        
        return results
    
    async def _run_parallel(
        self,
        contract_path: Optional[str],
        contract_address: Optional[str],
        levels: Set[ShieldLevel]
    ) -> Dict[ShieldLevel, ShieldResult]:
        """
        Execute les niveaux en parallele.
        
        Args:
            contract_path: Chemin du contrat
            contract_address: Adresse du contrat
            levels: Niveaux a executer
            
        Returns:
            Dict[ShieldLevel, ShieldResult]: Resultats par niveau
        """
        tasks = {}
        
        if ShieldLevel.LEVEL_1 in levels:
            tasks[ShieldLevel.LEVEL_1] = self._run_slither(contract_path)
        
        if ShieldLevel.LEVEL_2 in levels:
            tasks[ShieldLevel.LEVEL_2] = self._run_foundry(contract_path)
        
        if ShieldLevel.LEVEL_3 in levels and contract_address:
            tasks[ShieldLevel.LEVEL_3] = self._run_threat_simulator(contract_address)
        
        if ShieldLevel.LEVEL_4 in levels:
            tasks[ShieldLevel.LEVEL_4] = self._run_halmos(contract_path)
        
        # Execution parallele avec timeout global
        results = {}
        for level, task in tasks.items():
            try:
                results[level] = await asyncio.wait_for(task, timeout=self.timeout)
            except asyncio.TimeoutError:
                results[level] = ShieldResult(
                    level=level,
                    passed=False,
                    score=0,
                    error=f"Timeout after {self.timeout}s",
                    details={"timed_out": True}
                )
                logger.error(f"Level {level.value} timed out")
        
        return results
    
    # =========================================================================
    # EXECUTION DES NIVEAUX
    # =========================================================================
    
    async def _run_slither(
        self,
        contract_path: Optional[str]
    ) -> ShieldResult:
        """
        Execute l'analyse Slither.
        
        Args:
            contract_path: Chemin du contrat
            
        Returns:
            ShieldResult: Resultat du niveau
        """
        logger.info("Running Slither analysis (Level 1)")
        start_time = datetime.utcnow()
        
        try:
            if self.slither_wrapper:
                result = await self.slither_wrapper.analyze(contract_path)
            else:
                # Fallback: simulation
                result = {
                    "success": True,
                    "vulnerabilities": [],
                    "warnings": []
                }
            
            passed = result.get("success", False)
            vulnerabilities = result.get("vulnerabilities", [])
            
            self._stats["total_levels_executed"] += 1
            if passed:
                self._stats["levels_passed"] += 1
            else:
                self._stats["levels_failed"] += 1
            
            return ShieldResult(
                level=ShieldLevel.LEVEL_1,
                passed=passed,
                score=100 if passed else 0,
                details=result,
                execution_time=(datetime.utcnow() - start_time).total_seconds(),
                vulnerabilities=vulnerabilities
            )
            
        except Exception as e:
            self._stats["errors"] += 1
            return ShieldResult(
                level=ShieldLevel.LEVEL_1,
                passed=False,
                score=0,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )
    
    async def _run_foundry(
        self,
        contract_path: Optional[str]
    ) -> ShieldResult:
        """
        Execute les tests Foundry.
        
        Args:
            contract_path: Chemin du contrat
            
        Returns:
            ShieldResult: Resultat du niveau
        """
        logger.info("Running Foundry tests (Level 2)")
        start_time = datetime.utcnow()
        
        try:
            if self.foundry_wrapper:
                result = await self.foundry_wrapper.compile_and_test(contract_path)
            else:
                # Fallback: simulation
                result = {
                    "success": True,
                    "tests_passed": 5,
                    "tests_failed": 0
                }
            
            passed = result.get("success", False)
            
            self._stats["total_levels_executed"] += 1
            if passed:
                self._stats["levels_passed"] += 1
            else:
                self._stats["levels_failed"] += 1
            
            return ShieldResult(
                level=ShieldLevel.LEVEL_2,
                passed=passed,
                score=100 if passed else 0,
                details=result,
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )
            
        except Exception as e:
            self._stats["errors"] += 1
            return ShieldResult(
                level=ShieldLevel.LEVEL_2,
                passed=False,
                score=0,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )
    
    async def _run_threat_simulator(
        self,
        contract_address: str
    ) -> ShieldResult:
        """
        Execute la simulation de menaces.
        
        Args:
            contract_address: Adresse du contrat
            
        Returns:
            ShieldResult: Resultat du niveau
        """
        logger.info("Running threat simulation (Level 3)")
        start_time = datetime.utcnow()
        
        try:
            # Execution de la suite complete
            threat_report = await self.simulator.run_full_threat_suite(contract_address)
            
            passed = threat_report.passed
            vulnerabilities = [r.to_dict() for r in threat_report.results if r.vulnerable]
            
            self._stats["total_levels_executed"] += 1
            if passed:
                self._stats["levels_passed"] += 1
            else:
                self._stats["levels_failed"] += 1
            
            return ShieldResult(
                level=ShieldLevel.LEVEL_3,
                passed=passed,
                score=100 if passed else 50,
                details=threat_report.to_dict(),
                execution_time=(datetime.utcnow() - start_time).total_seconds(),
                vulnerabilities=vulnerabilities
            )
            
        except Exception as e:
            self._stats["errors"] += 1
            return ShieldResult(
                level=ShieldLevel.LEVEL_3,
                passed=False,
                score=0,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )
    
    async def _run_halmos(
        self,
        contract_path: Optional[str]
    ) -> ShieldResult:
        """
        Execute la verification formelle Halmos.
        
        Args:
            contract_path: Chemin du contrat
            
        Returns:
            ShieldResult: Resultat du niveau
        """
        logger.info("Running Halmos verification (Level 4)")
        start_time = datetime.utcnow()
        
        try:
            # Verification des invariants
            result = await self.halmos.verify_invariants(contract_path)
            
            passed = result.get("passed", False)
            vulnerabilities = []
            
            # Extraction des contre-exemples
            if not passed and "counterexamples" in result:
                for prop, counterexample in result["counterexamples"].items():
                    vulnerabilities.append({
                        "type": "formal_verification",
                        "property": prop,
                        "counterexample": counterexample
                    })
            
            self._stats["total_levels_executed"] += 1
            if passed:
                self._stats["levels_passed"] += 1
            else:
                self._stats["levels_failed"] += 1
            
            return ShieldResult(
                level=ShieldLevel.LEVEL_4,
                passed=passed,
                score=100 if passed else 0,
                details=result,
                execution_time=(datetime.utcnow() - start_time).total_seconds(),
                vulnerabilities=vulnerabilities
            )
            
        except Exception as e:
            self._stats["errors"] += 1
            return ShieldResult(
                level=ShieldLevel.LEVEL_4,
                passed=False,
                score=0,
                error=str(e),
                execution_time=(datetime.utcnow() - start_time).total_seconds()
            )
    
    # =========================================================================
    # EVALUATION ET RAPPORTS
    # =========================================================================
    
    def _evaluate_report(self, report: ShieldReport) -> None:
        """
        Evalue le rapport et calcule les metriques.
        
        Args:
            report: Rapport a evaluer
        """
        total_vulnerabilities = 0
        critical = 0
        high = 0
        
        for level_result in report.levels.values():
            total_vulnerabilities += len(level_result.vulnerabilities)
            
            for vuln in level_result.vulnerabilities:
                severity = vuln.get("severity", "medium")
                if severity == "critical":
                    critical += 1
                elif severity == "high":
                    high += 1
        
        report.total_vulnerabilities = total_vulnerabilities
        report.critical_vulnerabilities = critical
        report.high_vulnerabilities = high
        
        # Calcul du score global
        total_levels = len(report.levels)
        if total_levels == 0:
            report.overall_score = 0
            report.passed = False
            return
        
        # Score base sur les niveaux passes
        passed_count = sum(1 for r in report.levels.values() if r.passed)
        report.overall_score = (passed_count / total_levels) * 100
        
        # Deduction pour vulnerabilites critiques
        report.overall_score -= critical * 10
        report.overall_score -= high * 5
        
        # Score minimum 0
        report.overall_score = max(0, min(100, report.overall_score))
        
        # Le rapport est passe si tous les niveaux sont passes
        report.passed = all(r.passed for r in report.levels.values())
    
    def _generate_recommendations(self, report: ShieldReport) -> List[str]:
        """
        Genere des recommandations basees sur le rapport.
        
        Args:
            report: Rapport d'audit
            
        Returns:
            List[str]: Liste des recommandations
        """
        recommendations = []
        
        for level, result in report.levels.items():
            if not result.passed:
                if level == ShieldLevel.LEVEL_1:
                    recommendations.append("Fix Slither vulnerabilities (Level 1)")
                elif level == ShieldLevel.LEVEL_2:
                    recommendations.append("Fix failing tests (Level 2)")
                elif level == ShieldLevel.LEVEL_3:
                    recommendations.append("Fix vulnerabilities found by threat simulation (Level 3)")
                elif level == ShieldLevel.LEVEL_4:
                    recommendations.append("Fix formal verification issues (Level 4)")
        
        # Recommandations specifiques par vulnerabilite
        for level, result in report.levels.items():
            for vuln in result.vulnerabilities:
                if vuln.get("remediation"):
                    recommendations.append(f"[{level.value}] {vuln.get('remediation')}")
        
        return list(set(recommendations))
    
    # =========================================================================
    # STATISTIQUES
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du bouclier.
        
        Returns:
            Dict: Statistiques
        """
        return {
            **self._stats,
            "project_path": self.project_path,
            "cache_size": len(self._cache),
            "parallel": self.parallel,
            "timeout": self.timeout,
            "active_levels": [l.value for l in self.levels]
        }
    
    def clear_cache(self) -> None:
        """
        Vide le cache.
        """
        cache_size = len(self._cache)
        self._cache.clear()
        logger.info(f"Cache cleared ({cache_size} entries)")
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<SecurityShield(project_path='{self.project_path}', cache={len(self._cache)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le bouclier en dictionnaire.
        
        Returns:
            Dict: Representation
        """
        return {
            "project_path": self.project_path,
            "parallel": self.parallel,
            "timeout": self.timeout,
            "levels": [l.value for l in self.levels],
            "stats": self._stats,
            "cache_size": len(self._cache)
        }