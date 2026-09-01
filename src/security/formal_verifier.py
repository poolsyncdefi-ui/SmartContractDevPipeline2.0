# src/security/formal_verifier.py

"""
Formal verifier for the Smart Contract Dev Pipeline.
F31 – src/security/formal_verifier.py

Rôle Fonctionnel : Wrapper pour Halmos effectuant des preuves mathematiques symboliques.
Ce module implemente l'integration avec Halmos, un moteur de verification formelle
base sur Z3, pour effectuer des preuves symboliques sur les smart contracts.
Il supporte:
- La verification d'invariants
- La verification de proprietes personnalisees
- L'extraction de contre-exemples
- La generation de rapports detailles
- La verification de multiples contrats
- Les statistiques de verification

Le FormalVerifier est un composant du bouclier de securite multi-couches,
operant au niveau 4 (verification formelle).
"""
import asyncio
import subprocess
import os
import tempfile
import json
import re
from typing import Dict, Any, Optional, List, Tuple, Set
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
import logging

# Import des modules du pipeline
from src.core.exceptions import ValidationError
from src.config.settings import settings

# Configuration du logging
logger = logging.getLogger(__name__)


class VerificationResult(str, Enum):
    """
    Resultats possibles de la verification formelle.
    """
    PASSED = "passed"          # Verifie avec succes
    FAILED = "failed"          # Echec de la verification
    TIMEOUT = "timeout"        # Timeout
    ERROR = "error"            # Erreur d'execution
    UNKNOWN = "unknown"        # Resultat inconnu
    SKIPPED = "skipped"        # Verifiee ignoree


class PropertyType(str, Enum):
    """
    Types de proprietes verificables.
    """
    INVARIANT = "invariant"    # Invariant de contrat
    SAFETY = "safety"          # Propriete de securite
    LIVENESS = "liveness"      # Propriete de vivacite
    FAIRNESS = "fairness"      # Propriete d'equite
    CUSTOM = "custom"          # Propriete personnalisee


@dataclass
class VerificationProperty:
    """
    Propriete a verifier.
    
    Attributes:
        name (str): Nom de la propriete
        description (str): Description de la propriete
        type (PropertyType): Type de propriete
        expression (str): Expression a verifier
        function (Optional[str]): Fonction associee
        contract (Optional[str]): Contrat associe
        params (Dict): Parametres supplementaires
    """
    name: str
    description: str = ""
    type: PropertyType = PropertyType.INVARIANT
    expression: str = ""
    function: Optional[str] = None
    contract: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    
    def to_halmos_arg(self) -> str:
        """Convertit la propriete en argument Halmos."""
        if self.function:
            return f"--match-test {self.function}"
        return f"--match-test {self.name}"


@dataclass
class VerificationReport:
    """
    Rapport de verification formelle.
    
    Attributes:
        timestamp (datetime): Date du rapport
        contract_name (str): Nom du contrat verifie
        properties (List[VerificationProperty]): Proprietes verifiees
        results (Dict[str, VerificationResult]): Resultats par propriete
        counterexamples (Dict[str, str]): Contre-exemples par propriete
        passed_count (int): Nombre de proprietes verifiees
        failed_count (int): Nombre de proprietes en echec
        total_count (int): Nombre total de proprietes
        passed (bool): La verification est-elle reussie ?
        output (str): Sortie brute d'Halmos
        error (str): Erreur d'execution
        execution_time (float): Temps d'execution en secondes
        details (Dict): Details supplementaires
    """
    timestamp: datetime = field(default_factory=datetime.utcnow)
    contract_name: str = ""
    properties: List[VerificationProperty] = field(default_factory=list)
    results: Dict[str, VerificationResult] = field(default_factory=dict)
    counterexamples: Dict[str, str] = field(default_factory=dict)
    passed_count: int = 0
    failed_count: int = 0
    total_count: int = 0
    passed: bool = True
    output: str = ""
    error: str = ""
    execution_time: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le rapport en dictionnaire."""
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "contract_name": self.contract_name,
            "properties": [p.__dict__ for p in self.properties],
            "results": {k: v.value for k, v in self.results.items()},
            "counterexamples": self.counterexamples,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "total_count": self.total_count,
            "passed": self.passed,
            "output": self.output[:1000],
            "error": self.error[:500] if self.error else None,
            "execution_time": self.execution_time,
            "details": self.details
        }


class FormalVerifier:
    """
    Verificateur formel base sur Halmos.
    
    Cette classe fournit une interface complete pour la verification formelle
    de smart contracts avec Halmos.
    
    Attributes:
        project_path (str): Chemin du projet
        timeout (int): Timeout en secondes
        halmos_path (str): Chemin vers Halmos
        solc_path (str): Chemin vers solc
        _stats (Dict): Statistiques de verification
        _cache (Dict): Cache des resultats
    """
    
    # Proprietes predefinies pour les contrats ERC20
    ERC20_PROPERTIES = [
        VerificationProperty(
            name="totalSupply_invariant",
            description="Total supply must remain constant or increase",
            type=PropertyType.INVARIANT,
            expression="totalSupply() >= previous_totalSupply"
        ),
        VerificationProperty(
            name="balance_invariant",
            description="Sum of balances must equal total supply",
            type=PropertyType.INVARIANT,
            expression="sum(balances) == totalSupply()"
        ),
        VerificationProperty(
            name="transfer_safety",
            description="Transfer must not overflow",
            type=PropertyType.SAFETY,
            expression="transfer(from, to, amount) => balanceOf(from) >= amount"
        )
    ]
    
    def __init__(
        self,
        project_path: str = ".",
        timeout: int = 300,
        halmos_path: str = "halmos",
        solc_path: str = "solc"
    ):
        """
        Initialise le verificateur formel.
        
        Args:
            project_path: Chemin du projet
            timeout: Timeout en secondes (defaut: 300)
            halmos_path: Chemin vers Halmos (defaut: "halmos")
            solc_path: Chemin vers solc (defaut: "solc")
        """
        self.project_path = project_path
        self.timeout = timeout
        self.halmos_path = halmos_path
        self.solc_path = solc_path
        
        # Cache et statistiques
        self._cache: Dict[str, VerificationReport] = {}
        self._stats = {
            "total_verifications": 0,
            "passed_verifications": 0,
            "failed_verifications": 0,
            "timeouts": 0,
            "errors": 0,
            "total_properties": 0,
            "passed_properties": 0,
            "failed_properties": 0
        }
        
        logger.info(f"FormalVerifier initialized (timeout={timeout}s)")
    
    # =========================================================================
    # VERIFICATION D'INVARIANTS
    # =========================================================================
    
    async def verify_invariants(
        self,
        contract_path: Optional[str] = None,
        check_function: Optional[str] = None,
        properties: Optional[List[VerificationProperty]] = None,
        timeout: Optional[int] = None,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """
        Execute la verification formelle des invariants.
        
        Args:
            contract_path: Chemin du contrat (optionnel)
            check_function: Nom de la fonction a verifier (optionnel)
            properties: Liste des proprietes a verifier (optionnel)
            timeout: Timeout personnalise (optionnel)
            use_cache: Utiliser le cache (defaut: True)
            
        Returns:
            Dict: Resultat de la verification
        """
        start_time = datetime.utcnow()
        
        # Generation d'une cle de cache
        cache_key = f"{contract_path}_{check_function}_{timeout}"
        if use_cache and cache_key in self._cache:
            logger.info(f"Cache hit for {cache_key}")
            return self._cache[cache_key].to_dict()
        
        # Preparation des proprietes
        if not properties:
            properties = self.ERC20_PROPERTIES
        
        if check_function:
            # Filtrer les proprietes pour la fonction specifique
            properties = [p for p in properties if p.function == check_function]
        
        # Construction de la commande
        cmd = [self.halmos_path]
        
        if contract_path:
            cmd.append(contract_path)
        
        if properties:
            for prop in properties:
                cmd.append(prop.to_halmos_arg())
        
        if timeout:
            cmd.extend(["--timeout", str(timeout)])
        
        # Execution de Halmos
        result = await self._run_halmos(cmd, timeout or self.timeout)
        
        # Parsing du resultat
        report = self._parse_halmos_output(result, properties, contract_path)
        report.execution_time = (datetime.utcnow() - start_time).total_seconds()
        
        # Mise en cache
        if use_cache:
            self._cache[cache_key] = report
        
        # Mise a jour des statistiques
        self._stats["total_verifications"] += 1
        self._stats["total_properties"] += report.total_count
        self._stats["passed_properties"] += report.passed_count
        self._stats["failed_properties"] += report.failed_count
        
        if report.passed:
            self._stats["passed_verifications"] += 1
        else:
            self._stats["failed_verifications"] += 1
        
        logger.info(f"Verification completed: {report.passed_count}/{report.total_count} passed")
        
        return report.to_dict()
    
    async def verify_contract(
        self,
        contract_path: str,
        properties: Optional[List[VerificationProperty]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Verifie un contrat complet.
        
        Args:
            contract_path: Chemin du contrat
            properties: Proprietes a verifier (optionnel)
            timeout: Timeout personnalise (optionnel)
            
        Returns:
            Dict: Rapport de verification
        """
        logger.info(f"Verifying contract: {contract_path}")
        return await self.verify_invariants(
            contract_path=contract_path,
            properties=properties,
            timeout=timeout
        )
    
    async def verify_property(
        self,
        property_name: str,
        contract_path: Optional[str] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Verifie une propriete specifique.
        
        Args:
            property_name: Nom de la propriete
            contract_path: Chemin du contrat (optionnel)
            timeout: Timeout personnalise (optionnel)
            
        Returns:
            Dict: Resultat de la verification
        """
        return await self.verify_invariants(
            contract_path=contract_path,
            check_function=property_name,
            timeout=timeout
        )
    
    async def verify_erc20_contract(
        self,
        contract_path: str,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Verifie un contrat ERC20 avec les proprietes standard.
        
        Args:
            contract_path: Chemin du contrat
            timeout: Timeout personnalise (optionnel)
            
        Returns:
            Dict: Rapport de verification
        """
        return await self.verify_contract(
            contract_path=contract_path,
            properties=self.ERC20_PROPERTIES,
            timeout=timeout
        )
    
    # =========================================================================
    # EXECUTION D'HALMOS
    # =========================================================================
    
    async def _run_halmos(
        self,
        cmd: List[str],
        timeout: int
    ) -> Dict[str, Any]:
        """
        Execute Halmos avec les parametres donnes.
        
        Args:
            cmd: Commande et arguments
            timeout: Timeout en secondes
            
        Returns:
            Dict: Resultat de l'execution
        """
        try:
            # Execution du processus
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                self._stats["timeouts"] += 1
                return {
                    "success": False,
                    "output": "",
                    "error": f"Timeout after {timeout}s",
                    "returncode": -1,
                    "timed_out": True
                }
            
            output = stdout.decode('utf-8', errors='ignore')
            error = stderr.decode('utf-8', errors='ignore')
            
            return {
                "success": proc.returncode == 0,
                "output": output,
                "error": error,
                "returncode": proc.returncode,
                "timed_out": False
            }
            
        except FileNotFoundError:
            self._stats["errors"] += 1
            logger.error(f"Halmos not found: {self.halmos_path}")
            return {
                "success": False,
                "output": "",
                "error": "Halmos not found. Please install.",
                "returncode": -1,
                "timed_out": False
            }
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Halmos execution failed: {str(e)}")
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "returncode": -1,
                "timed_out": False
            }
    
    # =========================================================================
    # PARSING DES RESULTATS
    # =========================================================================
    
    def _parse_halmos_output(
        self,
        result: Dict[str, Any],
        properties: List[VerificationProperty],
        contract_path: Optional[str]
    ) -> VerificationReport:
        """
        Parse la sortie d'Halmos.
        
        Args:
            result: Resultat de l'execution
            properties: Proprietes verifiees
            contract_path: Chemin du contrat
            
        Returns:
            VerificationReport: Rapport de verification
        """
        report = VerificationReport(
            contract_name=os.path.basename(contract_path) if contract_path else "unknown",
            properties=properties,
            output=result.get("output", ""),
            error=result.get("error", "")
        )
        
        # Si l'execution a echoue
        if not result.get("success", False):
            report.passed = False
            for prop in properties:
                report.results[prop.name] = VerificationResult.ERROR
            return report
        
        output = result.get("output", "")
        
        # Parsing des resultats
        for prop in properties:
            result_key = self._determine_result(prop, output)
            report.results[prop.name] = result_key
            
            if result_key == VerificationResult.PASSED:
                report.passed_count += 1
            elif result_key == VerificationResult.FAILED:
                report.failed_count += 1
                # Extraction du contre-exemple
                counterexample = self._extract_counterexample(prop, output)
                if counterexample:
                    report.counterexamples[prop.name] = counterexample
        
        report.total_count = len(properties)
        report.passed = report.failed_count == 0
        
        # Ajout des details supplementaires
        report.details = self._extract_details(output)
        
        return report
    
    def _determine_result(
        self,
        prop: VerificationProperty,
        output: str
    ) -> VerificationResult:
        """
        Determine le resultat d'une propriete.
        
        Args:
            prop: Propriete verifiee
            output: Sortie d'Halmos
            
        Returns:
            VerificationResult: Resultat de la verification
        """
        # Recherche de patterns dans la sortie
        if f"PASSED: {prop.name}" in output or f"PASSED: {prop.function}" in output:
            return VerificationResult.PASSED
        
        if f"FAILED: {prop.name}" in output or f"FAILED: {prop.function}" in output:
            return VerificationResult.FAILED
        
        if "Violated" in output and prop.name in output:
            return VerificationResult.FAILED
        
        if "Timeout" in output:
            return VerificationResult.TIMEOUT
        
        if "Error" in output:
            return VerificationResult.ERROR
        
        return VerificationResult.UNKNOWN
    
    def _extract_counterexample(
        self,
        prop: VerificationProperty,
        output: str
    ) -> Optional[str]:
        """
        Extrait le contre-exemple de la sortie.
        
        Args:
            prop: Propriete verifiee
            output: Sortie d'Halmos
            
        Returns:
            Optional[str]: Contre-exemple ou None
        """
        # Recherche du contre-exemple dans la sortie
        patterns = [
            rf"Counterexample for {prop.name}: (.+)",
            rf"Violated: (.+)",
            rf"Counterexample: (.+)",
            r"Counterexample: \n(.+)"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
        
        # Si pas de contre-exemple structure, extraire les lignes pertinentes
        lines = output.split('\n')
        for i, line in enumerate(lines):
            if prop.name in line and "Counterexample" in line:
                return '\n'.join(lines[i:i+10])
        
        return None
    
    def _extract_details(self, output: str) -> Dict[str, Any]:
        """
        Extrait les details supplementaires de la sortie.
        
        Args:
            output: Sortie d'Halmos
            
        Returns:
            Dict: Details extraits
        """
        details = {}
        
        # Extraction des statistiques
        stats_match = re.search(r"(\d+) properties verified", output)
        if stats_match:
            details["properties_verified"] = int(stats_match.group(1))
        
        time_match = re.search(r"Time: (\d+\.?\d*)s", output)
        if time_match:
            details["verification_time"] = float(time_match.group(1))
        
        return details
    
    # =========================================================================
    # GENERATION DE RAPPORTS
    # =========================================================================
    
    def generate_report_summary(self, report: VerificationReport) -> str:
        """
        Genere un resume du rapport de verification.
        
        Args:
            report: Rapport de verification
            
        Returns:
            str: Resume du rapport
        """
        lines = [
            "🔬 Formal Verification Report",
            "=" * 40,
            f"Contract: {report.contract_name}",
            f"Timestamp: {report.timestamp.isoformat()}",
            f"Total properties: {report.total_count}",
            f"Passed: {report.passed_count}",
            f"Failed: {report.failed_count}",
            f"Status: {'✅ PASSED' if report.passed else '❌ FAILED'}",
            "",
            "📋 Property Results:"
        ]
        
        for prop in report.properties:
            result = report.results.get(prop.name, VerificationResult.UNKNOWN)
            status_icon = "✅" if result == VerificationResult.PASSED else "❌" if result == VerificationResult.FAILED else "⚠️"
            lines.append(f"  {status_icon} {prop.name}: {result.value}")
            
            if prop.name in report.counterexamples:
                lines.append(f"     Counterexample: {report.counterexamples[prop.name][:100]}...")
        
        if report.failed_count > 0:
            lines.append("")
            lines.append("💡 Recommendations:")
            for prop in report.properties:
                if prop.name in report.counterexamples:
                    lines.append(f"  - Fix {prop.name}: Check the counterexample above")
        
        lines.append("")
        lines.append("=" * 40)
        
        return "\n".join(lines)
    
    # =========================================================================
    # STATISTIQUES
    # =========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du verificateur.
        
        Returns:
            Dict: Statistiques
        """
        return {
            **self._stats,
            "cache_size": len(self._cache),
            "project_path": self.project_path,
            "timeout": self.timeout
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
        return f"<FormalVerifier(project_path='{self.project_path}', cache={len(self._cache)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le verificateur en dictionnaire.
        
        Returns:
            Dict: Representation
        """
        return {
            "project_path": self.project_path,
            "timeout": self.timeout,
            "cache_size": len(self._cache),
            "stats": self._stats
        }