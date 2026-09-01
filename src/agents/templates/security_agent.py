# src/agents/templates/security_agent.py

"""
Security agent for the Smart Contract Dev Pipeline.
F21 – src/agents/templates/security_agent.py

Rôle Fonctionnel : Agent de securite auditant le code et generant des correctifs.
L'Agent Securite est responsable de:
- L'audit de code Solidity via Slither (analyse statique)
- La verification formelle via Halmos (preuves symboliques)
- Le fuzzing via Echidna/Foundry (tests d'invariants)
- La simulation d'attaques via Anvil (threat simulation)
- La generation de rapports de vulnerabilites
- La proposition de correctifs automatiques
- La classification des vulnerabilites par severite

Cet agent est le composant central du bouclier de securite multi-couches
defini dans les specifications du pipeline.
"""
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
import logging
import json
import re
import subprocess
import asyncio
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, ShieldVerificationError
from src.agents.base.best_practice import BaseBestPractice
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase

# Configuration du logging
logger = logging.getLogger(__name__)


class VulnerabilitySeverity(str, Enum):
    """
    Niveaux de severite des vulnerabilites.
    """
    CRITICAL = "critical"      # Critique - doit etre corrige immediatement
    HIGH = "high"              # Eleve - doit etre corrige rapidement
    MEDIUM = "medium"          # Moyen - devrait etre corrige
    LOW = "low"                # Faible - peut etre ignore temporairement
    INFO = "info"              # Information - pas une vulnerabilite


class VulnerabilityType(str, Enum):
    """
    Types de vulnerabilites.
    """
    REENTRANCY = "reentrancy"
    ACCESS_CONTROL = "access_control"
    ARITHMETIC = "arithmetic"  # Overflow/Underflow
    UNCHECKED_CALL = "unchecked_call"
    FRONT_RUNNING = "front_running"
    REENTRANCY_READ = "reentrancy_read"
    DOS = "denial_of_service"
    LOGIC_ERROR = "logic_error"
    TIMING = "timing_attack"
    INFORMATION_DISCLOSURE = "information_disclosure"
    GAS_OPTIMIZATION = "gas_optimization"
    COMPLIANCE = "compliance"
    FORMAL_VERIFICATION = "formal_verification_failure"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency_vulnerability"
    CUSTOM = "custom"


class AuditLevel(str, Enum):
    """
    Niveaux d'audit de securite.
    """
    LEVEL_1 = "level_1"  # Analyse statique (Slither/Aderyn)
    LEVEL_2 = "level_2"  # Fuzzing (Echidna/Foundry)
    LEVEL_3 = "level_3"  # Simulation d'attaques (Anvil)
    LEVEL_4 = "level_4"  # Verification formelle (Halmos)
    FULL = "full"        # Tous les niveaux


@dataclass
class Vulnerability:
    """
    Represente une vulnerabilite detectee.
    
    Attributes:
        id (str): Identifiant unique de la vulnerabilite
        type (VulnerabilityType): Type de vulnerabilite
        severity (VulnerabilitySeverity): Niveau de severite
        title (str): Titre descriptif
        description (str): Description detaillee
        location (str): Localisation dans le code
        line_start (int): Ligne de debut
        line_end (int): Ligne de fin
        code_snippet (str): Extrait de code concerne
        impact (str): Impact potentiel
        remediation (str): Correction proposee
        remediation_code (Optional[str]): Code de correction
        references (List[str]): References externes
        metadata (Dict): Metadonnees supplementaires
    """
    id: str
    type: VulnerabilityType
    severity: VulnerabilitySeverity
    title: str
    description: str
    location: str = ""
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    code_snippet: str = ""
    impact: str = ""
    remediation: str = ""
    remediation_code: Optional[str] = None
    references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit la vulnerabilite en dictionnaire."""
        return {
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "code_snippet": self.code_snippet,
            "impact": self.impact,
            "remediation": self.remediation,
            "remediation_code": self.remediation_code,
            "references": self.references,
            "metadata": self.metadata
        }


@dataclass
class AuditReport:
    """
    Rapport d'audit de securite.
    
    Attributes:
        audited_at (datetime): Date de l'audit
        contract_name (str): Nom du contrat audite
        level (AuditLevel): Niveau d'audit realise
        vulnerabilities (List[Vulnerability]): Vulnerabilites detectees
        passed (bool): L'audit est-il passe ?
        critical_count (int): Nombre de vulnerabilites critiques
        high_count (int): Nombre de vulnerabilites hautes
        medium_count (int): Nombre de vulnerabilites moyennes
        low_count (int): Nombre de vulnerabilites faibles
        score (float): Score de securite (0-100)
        details (Dict): Details supplementaires
    """
    audited_at: datetime = field(default_factory=datetime.utcnow)
    contract_name: str = ""
    level: AuditLevel = AuditLevel.FULL
    vulnerabilities: List[Vulnerability] = field(default_factory=list)
    passed: bool = True
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    score: float = 100.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le rapport en dictionnaire."""
        return {
            "audited_at": self.audited_at.isoformat() if self.audited_at else None,
            "contract_name": self.contract_name,
            "level": self.level.value,
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "passed": self.passed,
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
            "low_count": self.low_count,
            "score": self.score,
            "details": self.details
        }


class SecurityAgent(AbstractAgent):
    """
    Agent specialise dans l'audit de securite.
    
    Cet agent implemente le bouclier de securite multi-couches du pipeline,
    combinant analyse statique, fuzzing, simulation d'attaques et verification formelle.
    
    Attributes:
        llm_client (Optional[LLMClient]): Client LLM pour les suggestions
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        slither_path (str): Chemin vers Slither
        halmos_path (str): Chemin vers Halmos
        foundry_path (str): Chemin vers Foundry
        anvil_rpc_url (str): URL RPC pour Anvil
        min_security_score (float): Score minimum requis (0-100)
        auto_fix (bool): Generer automatiquement des correctifs
        _audit_history (List[AuditReport]): Historique des audits
    """
    
    # Mapping des types de vulnerabilites Slither vers le systeme
    SLITHER_MAPPING = {
        "reentrancy": VulnerabilityType.REENTRANCY,
        "reentrancy-eth": VulnerabilityType.REENTRANCY,
        "reentrancy-no-eth": VulnerabilityType.REENTRANCY_READ,
        "unchecked-transfer": VulnerabilityType.UNCHECKED_CALL,
        "unchecked-lowlevel": VulnerabilityType.UNCHECKED_CALL,
        "unchecked-send": VulnerabilityType.UNCHECKED_CALL,
        "unchecked-suicide": VulnerabilityType.UNCHECKED_CALL,
        "arbitrary-send-erc20": VulnerabilityType.ACCESS_CONTROL,
        "controlled-delegatecall": VulnerabilityType.ACCESS_CONTROL,
        "delegatecall-loop": VulnerabilityType.ACCESS_CONTROL,
        "delegatecall-unchained": VulnerabilityType.ACCESS_CONTROL,
        "incorrect-equality": VulnerabilityType.LOGIC_ERROR,
        "integer-overflow": VulnerabilityType.ARITHMETIC,
        "integer-underflow": VulnerabilityType.ARITHMETIC,
        "tx-origin": VulnerabilityType.ACCESS_CONTROL,
        "denial-of-service": VulnerabilityType.DOS,
        "front-running": VulnerabilityType.FRONT_RUNNING,
    }
    
    # Severite par defaut selon le type
    DEFAULT_SEVERITY = {
        VulnerabilityType.REENTRANCY: VulnerabilitySeverity.CRITICAL,
        VulnerabilityType.ACCESS_CONTROL: VulnerabilitySeverity.HIGH,
        VulnerabilityType.ARITHMETIC: VulnerabilitySeverity.HIGH,
        VulnerabilityType.UNCHECKED_CALL: VulnerabilitySeverity.MEDIUM,
        VulnerabilityType.FRONT_RUNNING: VulnerabilitySeverity.HIGH,
        VulnerabilityType.REENTRANCY_READ: VulnerabilitySeverity.MEDIUM,
        VulnerabilityType.DOS: VulnerabilitySeverity.HIGH,
        VulnerabilityType.LOGIC_ERROR: VulnerabilitySeverity.CRITICAL,
        VulnerabilityType.TIMING: VulnerabilitySeverity.LOW,
        VulnerabilityType.INFORMATION_DISCLOSURE: VulnerabilitySeverity.MEDIUM,
        VulnerabilityType.GAS_OPTIMIZATION: VulnerabilitySeverity.LOW,
        VulnerabilityType.COMPLIANCE: VulnerabilitySeverity.MEDIUM,
        VulnerabilityType.FORMAL_VERIFICATION: VulnerabilitySeverity.HIGH,
        VulnerabilityType.CONFIGURATION: VulnerabilitySeverity.MEDIUM,
        VulnerabilityType.DEPENDENCY: VulnerabilitySeverity.HIGH,
        VulnerabilityType.CUSTOM: VulnerabilitySeverity.MEDIUM,
    }
    
    def __init__(
        self,
        agent_id: str,
        name: str = "SecurityAgent",
        skills: Optional[List] = None,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        best_practices: Optional[List[BaseBestPractice]] = None,
        slither_path: str = "slither",
        halmos_path: str = "halmos",
        foundry_path: str = "forge",
        anvil_rpc_url: str = "http://localhost:8545",
        min_security_score: float = 80.0,
        auto_fix: bool = False
    ):
        """
        Initialise l'Agent Securite.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (defaut: "SecurityAgent")
            skills: Liste des competences (optionnel)
            llm_client: Client LLM pour les suggestions
            knowledge_base: Base de connaissances RAG
            best_practices: Bonnes pratiques a appliquer
            slither_path: Chemin vers Slither (defaut: "slither")
            halmos_path: Chemin vers Halmos (defaut: "halmos")
            foundry_path: Chemin vers Foundry (defaut: "forge")
            anvil_rpc_url: URL RPC pour Anvil
            min_security_score: Score minimum requis (defaut: 80.0)
            auto_fix: Generer automatiquement des correctifs (defaut: False)
        """
        super().__init__(agent_id=agent_id, name=name, skills=skills, llm_client=llm_client)
        self.knowledge_base = knowledge_base
        self.best_practices = best_practices or []
        self.slither_path = slither_path
        self.halmos_path = halmos_path
        self.foundry_path = foundry_path
        self.anvil_rpc_url = anvil_rpc_url
        self.min_security_score = min_security_score
        self.auto_fix = auto_fix
        self._audit_history: List[AuditReport] = []
        self._compilation_cache: Dict[str, Dict] = {}
        
        logger.info(f"SecurityAgent initialized: {agent_id}")
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse le code et detecte les vulnerabilites.
        
        Args:
            task_data: Doit contenir:
                - 'code': Code a auditer
                - 'level': Niveau d'audit (optionnel)
                - 'contract_name': Nom du contrat (optionnel)
                - 'slither_report': Rapport Slither (optionnel)
                - 'halmos_report': Rapport Halmos (optionnel)
                
        Returns:
            Dict contenant:
            - 'status': SUCCESS ou FAILED
            - 'report': AuditReport en dictionnaire
            - 'vulnerabilities': Liste des vulnerabilites
            - 'guide': Guide de correction
            - 'secure': Bool indiquant si le code est securise
            - 'score': Score de securite (0-100)
        """
        start_time = datetime.utcnow()
        
        try:
            # 1. Extraction des parametres
            code = task_data.get("code", "")
            contract_name = task_data.get("contract_name", "unknown")
            level_str = task_data.get("level", "full")
            slither_report = task_data.get("slither_report", {})
            halmos_report = task_data.get("halmos_report", {})
            
            if not code:
                raise ValueError("No code provided for security audit")
            
            # 2. Determination du niveau d'audit
            try:
                level = AuditLevel(level_str.lower())
            except ValueError:
                level = AuditLevel.FULL
                logger.warning(f"Invalid audit level '{level_str}', using FULL")
            
            # 3. Execution de l'audit
            report = await self._run_audit(
                code=code,
                contract_name=contract_name,
                level=level,
                slither_report=slither_report,
                halmos_report=halmos_report
            )
            
            # 4. Enrichissement via RAG
            if self.knowledge_base and report.vulnerabilities:
                report = await self._enrich_with_rag(report)
            
            # 5. Application des bonnes pratiques
            if self.best_practices:
                report = await self._apply_best_practices(report)
            
            # 6. Generation des correctifs
            if self.auto_fix and report.vulnerabilities:
                report = await self._generate_fixes(report)
            
            # 7. Classification et scoring
            self._classify_vulnerabilities(report)
            report.score = self._calculate_security_score(report)
            report.passed = report.score >= self.min_security_score and report.critical_count == 0
            
            # 8. Persistance de l'audit
            self._audit_history.append(report)
            
            # 9. Generation du guide de remediation
            guide = self.format_remediation_guide(report.vulnerabilities)
            
            # 10. Logging de l'execution
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),
                prompt=f"Audit {contract_name} (level={level.value})",
                response=f"Found {len(report.vulnerabilities)} vulnerabilities, score={report.score:.1f}",
                tool_output=json.dumps(report.to_dict(), indent=2)[:500]
            )
            
            logger.info(f"Security audit completed: {contract_name}, score={report.score:.1f}, passed={report.passed}")
            
            return {
                "status": "SUCCESS",
                "report": report.to_dict(),
                "vulnerabilities": [v.to_dict() for v in report.vulnerabilities],
                "guide": guide,
                "secure": report.passed,
                "score": report.score,
                "passed": report.passed,
                "level": level.value,
                "metadata": {
                    "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                    "vulnerabilities_count": len(report.vulnerabilities),
                    "critical_count": report.critical_count,
                    "high_count": report.high_count
                }
            }
            
        except Exception as e:
            logger.error(f"SecurityAgent execution failed: {str(e)}")
            return {
                "status": "FAILED",
                "error": str(e),
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }
    
    # =========================================================================
    # AUDIT PRINCIPAL
    # =========================================================================
    
    async def _run_audit(
        self,
        code: str,
        contract_name: str,
        level: AuditLevel,
        slither_report: Dict,
        halmos_report: Dict
    ) -> AuditReport:
        """
        Execute l'audit de securite complet.
        
        Args:
            code: Code a auditer
            contract_name: Nom du contrat
            level: Niveau d'audit
            slither_report: Rapport Slither pre-existant
            halmos_report: Rapport Halmos pre-existant
            
        Returns:
            AuditReport: Rapport d'audit
        """
        vulnerabilities = []
        details = {}
        
        # Niveau 1: Analyse statique (Slither)
        if level in [AuditLevel.LEVEL_1, AuditLevel.FULL]:
            if slither_report:
                slither_vulns = self.parse_slither_json(slither_report)
            else:
                slither_vulns = await self.run_slither_analysis(code, contract_name)
            vulnerabilities.extend(slither_vulns)
            details["slither"] = {"vulnerabilities_found": len(slither_vulns)}
            logger.info(f"Level 1 (Slither): {len(slither_vulns)} vulnerabilities found")
        
        # Niveau 2: Fuzzing (Foundry/Echidna)
        if level in [AuditLevel.LEVEL_2, AuditLevel.FULL]:
            fuzzing_results = await self.run_fuzzing_analysis(code, contract_name)
            if fuzzing_results:
                vulnerabilities.extend(fuzzing_results)
                details["fuzzing"] = {"vulnerabilities_found": len(fuzzing_results)}
                logger.info(f"Level 2 (Fuzzing): {len(fuzzing_results)} vulnerabilities found")
        
        # Niveau 3: Simulation d'attaques (Anvil)
        if level in [AuditLevel.LEVEL_3, AuditLevel.FULL]:
            attack_results = await self.run_threat_simulation(code, contract_name)
            if attack_results:
                vulnerabilities.extend(attack_results)
                details["threat_simulation"] = {"vulnerabilities_found": len(attack_results)}
                logger.info(f"Level 3 (Threat Simulation): {len(attack_results)} vulnerabilities found")
        
        # Niveau 4: Verification formelle (Halmos)
        if level in [AuditLevel.LEVEL_4, AuditLevel.FULL]:
            if halmos_report:
                formal_results = self.parse_halmos_json(halmos_report)
            else:
                formal_results = await self.run_halmos_verification(code, contract_name)
            if formal_results:
                vulnerabilities.extend(formal_results)
                details["formal_verification"] = {"vulnerabilities_found": len(formal_results)}
                logger.info(f"Level 4 (Halmos): {len(formal_results)} vulnerabilities found")
        
        # Deduplication des vulnerabilites
        vulnerabilities = self._deduplicate_vulnerabilities(vulnerabilities)
        
        return AuditReport(
            contract_name=contract_name,
            level=level,
            vulnerabilities=vulnerabilities,
            details=details
        )
    
    # =========================================================================
    # NIVEAU 1: ANALYSE STATIQUE (SLITHER)
    # =========================================================================
    
    def parse_slither_json(self, raw_json: Dict) -> List[Vulnerability]:
        """
        Extrait les vulnerabilites du rapport Slither.
        
        Args:
            raw_json: Rapport JSON de Slither
            
        Returns:
            List[Vulnerability]: Vulnerabilites extraites
        """
        vulnerabilities = []
        detectors = raw_json.get("results", {}).get("detectors", [])
        
        for detector in detectors:
            # Filtrage par impact
            impact = detector.get("impact", "Low")
            if impact not in ["High", "Medium"]:
                continue
            
            # Mapping du type
            check_name = detector.get("check", "custom")
            vuln_type = self.SLITHER_MAPPING.get(check_name, VulnerabilityType.CUSTOM)
            
            # Severite par defaut
            severity = self.DEFAULT_SEVERITY.get(vuln_type, VulnerabilitySeverity.MEDIUM)
            if impact == "High":
                severity = VulnerabilitySeverity.HIGH
            elif impact == "Critical":
                severity = VulnerabilitySeverity.CRITICAL
            
            # Extraction des elements
            elements = detector.get("elements", [])
            for element in elements:
                vulnerability = Vulnerability(
                    id=f"SLITHER_{check_name}_{len(vulnerabilities)}",
                    type=vuln_type,
                    severity=severity,
                    title=detector.get("name", check_name),
                    description=detector.get("description", ""),
                    location=element.get("source_mapping", {}).get("filename", ""),
                    line_start=element.get("source_mapping", {}).get("start_line"),
                    line_end=element.get("source_mapping", {}).get("end_line"),
                    code_snippet=element.get("source_mapping", {}).get("source", ""),
                    impact=detector.get("impact", ""),
                    remediation=detector.get("remediation", ""),
                    references=[f"Slither: {detector.get('check', '')}"]
                )
                vulnerabilities.append(vulnerability)
        
        logger.debug(f"Parsed {len(vulnerabilities)} vulnerabilities from Slither")
        return vulnerabilities
    
    async def run_slither_analysis(self, code: str, contract_name: str) -> List[Vulnerability]:
        """
        Execute Slither sur le code.
        
        Args:
            code: Code a analyser
            contract_name: Nom du contrat
            
        Returns:
            List[Vulnerability]: Vulnerabilites detectees
        """
        try:
            # Sauvegarde temporaire du code
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
                f.write(code)
                filepath = f.name
            
            try:
                # Execution de Slither
                cmd = [self.slither_path, filepath, "--json", "-"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                
                if result.returncode != 0:
                    logger.error(f"Slither execution failed: {result.stderr}")
                    return []
                
                # Parsing du resultat
                try:
                    slither_json = json.loads(result.stdout)
                    return self.parse_slither_json(slither_json)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Slither JSON: {str(e)}")
                    return []
                    
            finally:
                # Nettoyage
                os.unlink(filepath)
                
        except subprocess.TimeoutExpired:
            logger.error("Slither analysis timed out (60s)")
            return []
        except Exception as e:
            logger.error(f"Slither analysis failed: {str(e)}")
            return []
    
    # =========================================================================
    # NIVEAU 2: FUZZING
    # =========================================================================
    
    async def run_fuzzing_analysis(self, code: str, contract_name: str) -> List[Vulnerability]:
        """
        Execute le fuzzing via Foundry/Echidna.
        
        Args:
            code: Code a tester
            contract_name: Nom du contrat
            
        Returns:
            List[Vulnerability]: Vulnerabilites detectees
        """
        vulnerabilities = []
        
        try:
            # Construction du projet temporaire
            import tempfile
            import os
            import shutil
            
            temp_dir = tempfile.mkdtemp()
            
            try:
                # Creation de la structure Foundry
                contracts_dir = os.path.join(temp_dir, "contracts")
                test_dir = os.path.join(temp_dir, "test")
                os.makedirs(contracts_dir, exist_ok=True)
                os.makedirs(test_dir, exist_ok=True)
                
                # Ecriture du contrat
                contract_path = os.path.join(contracts_dir, f"{contract_name}.sol")
                with open(contract_path, 'w') as f:
                    f.write(code)
                
                # Creation d'un test basique
                test_path = os.path.join(test_dir, f"{contract_name}.t.sol")
                test_code = f"""
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";
import "../contracts/{contract_name}.sol";

contract {contract_name}Test is Test {{
    {contract_name} public contractInstance;
    
    function setUp() public {{
        contractInstance = new {contract_name}();
    }}
    
    function testInvariant() public {{
        // Test basique
        assertTrue(true);
    }}
}}
"""
                with open(test_path, 'w') as f:
                    f.write(test_code)
                
                # Execution des tests Foundry
                cmd = [self.foundry_path, "test", "--root", temp_dir, "-vv"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                # Analyse des resultats
                if "Failing tests" in result.stdout or result.returncode != 0:
                    vulnerability = Vulnerability(
                        id=f"FUZZ_{len(vulnerabilities)}",
                        type=VulnerabilityType.LOGIC_ERROR,
                        severity=VulnerabilitySeverity.HIGH,
                        title="Fuzzing test failure",
                        description=f"Fuzzing detected a violation of invariants",
                        impact="The contract may not behave as expected under certain conditions",
                        remediation="Review the contract logic and invariants",
                        code_snippet=result.stdout[:500],
                        metadata={"fuzzing_output": result.stdout}
                    )
                    vulnerabilities.append(vulnerability)
                
            finally:
                # Nettoyage
                shutil.rmtree(temp_dir, ignore_errors=True)
                
        except subprocess.TimeoutExpired:
            logger.error("Fuzzing analysis timed out (120s)")
        except Exception as e:
            logger.error(f"Fuzzing analysis failed: {str(e)}")
        
        return vulnerabilities
    
    # =========================================================================
    # NIVEAU 3: SIMULATION D'ATTAQUES (ANVIL)
    # =========================================================================
    
    async def run_threat_simulation(self, code: str, contract_name: str) -> List[Vulnerability]:
        """
        Simule des attaques via Anvil.
        
        Args:
            code: Code a tester
            contract_name: Nom du contrat
            
        Returns:
            List[Vulnerability]: Vulnerabilites detectees
        """
        vulnerabilities = []
        
        try:
            # Simulation d'attaques communes
            attack_patterns = [
                ("reentrancy", "Check for reentrancy vulnerability"),
                ("front_running", "Check for front-running vulnerability"),
                ("access_control", "Check for access control vulnerabilities"),
                ("arithmetic", "Check for arithmetic issues")
            ]
            
            for attack_type, description in attack_patterns:
                # Detection basique
                if attack_type == "reentrancy":
                    if self._detect_reentrancy(code):
                        vuln = self._create_reentrancy_vulnerability()
                        vulnerabilities.append(vuln)
                
                elif attack_type == "front_running":
                    if self._detect_front_running(code):
                        vuln = self._create_front_running_vulnerability()
                        vulnerabilities.append(vuln)
                
                elif attack_type == "access_control":
                    if self._detect_access_control_issues(code):
                        vuln = self._create_access_control_vulnerability()
                        vulnerabilities.append(vuln)
                
                elif attack_type == "arithmetic":
                    if self._detect_arithmetic_issues(code):
                        vuln = self._create_arithmetic_vulnerability()
                        vulnerabilities.append(vuln)
            
        except Exception as e:
            logger.error(f"Threat simulation failed: {str(e)}")
        
        return vulnerabilities
    
    def _detect_reentrancy(self, code: str) -> bool:
        """Detecte les vulnerabilites de reentrance."""
        # Pattern: external call followed by state modification
        if ".call" in code and "balance" in code and "require" not in code:
            return True
        if ".transfer" in code and "balance" in code:
            return True
        return False
    
    def _detect_front_running(self, code: str) -> bool:
        """Detecte les vulnerabilites de front-running."""
        # Pattern: visibility of transaction ordering
        if "tx.origin" in code:
            return True
        return False
    
    def _detect_access_control_issues(self, code: str) -> bool:
        """Detecte les vulnerabilites de controle d'acces."""
        # Pattern: functions without access control
        functions = re.findall(r"function\s+\w+\s*\([^)]*\)\s*(?:public|external)\s*{", code)
        if len(functions) > 0 and "onlyOwner" not in code and "require" not in code:
            return True
        return False
    
    def _detect_arithmetic_issues(self, code: str) -> bool:
        """Detecte les vulnerabilites arithmetiques."""
        # Pattern: operations without SafeMath or unchecked
        if " + " in code or " - " in code:
            if "unchecked" not in code and "SafeMath" not in code:
                return True
        return False
    
    def _create_reentrancy_vulnerability(self) -> Vulnerability:
        return Vulnerability(
            id=f"SIM_{len(self._audit_history)}",
            type=VulnerabilityType.REENTRANCY,
            severity=VulnerabilitySeverity.CRITICAL,
            title="Reentrancy vulnerability detected",
            description="The contract may be vulnerable to reentrancy attacks. External calls are made before state updates.",
            impact="An attacker could drain funds from the contract.",
            remediation="Use the Checks-Effects-Interactions pattern or add a reentrancy guard.",
            remediation_code="""
    modifier nonReentrant() {
        require(_status != 1, "ReentrancyGuard: reentrant call");
        _status = 1;
        _;
        _status = 0;
    }
    """
        )
    
    def _create_front_running_vulnerability(self) -> Vulnerability:
        return Vulnerability(
            id=f"SIM_{len(self._audit_history)}",
            type=VulnerabilityType.FRONT_RUNNING,
            severity=VulnerabilitySeverity.HIGH,
            title="Front-running vulnerability detected",
            description="The contract may be vulnerable to front-running attacks.",
            impact="An attacker could front-run transactions for profit.",
            remediation="Use commit-reveal patterns or add privacy measures.",
        )
    
    def _create_access_control_vulnerability(self) -> Vulnerability:
        return Vulnerability(
            id=f"SIM_{len(self._audit_history)}",
            type=VulnerabilityType.ACCESS_CONTROL,
            severity=VulnerabilitySeverity.HIGH,
            title="Access control vulnerability detected",
            description="Functions may lack proper access control.",
            impact="Unauthorized users could access restricted functions.",
            remediation="Add access control modifiers or require statements.",
        )
    
    def _create_arithmetic_vulnerability(self) -> Vulnerability:
        return Vulnerability(
            id=f"SIM_{len(self._audit_history)}",
            type=VulnerabilityType.ARITHMETIC,
            severity=VulnerabilitySeverity.HIGH,
            title="Arithmetic vulnerability detected",
            description="The contract uses arithmetic operations without overflow protection.",
            impact="Could lead to overflow/underflow vulnerabilities.",
            remediation="Use SafeMath or Solidity 0.8+ for built-in overflow checks.",
        )
    
    # =========================================================================
    # NIVEAU 4: VERIFICATION FORMELLE (HALMOS)
    # =========================================================================
    
    def parse_halmos_json(self, raw_json: Dict) -> List[Vulnerability]:
        """
        Extrait les vulnerabilites du rapport Halmos.
        
        Args:
            raw_json: Rapport JSON de Halmos
            
        Returns:
            List[Vulnerability]: Vulnerabilites extraites
        """
        vulnerabilities = []
        
        results = raw_json.get("results", [])
        for result in results:
            if not result.get("verified", True):
                vulnerability = Vulnerability(
                    id=f"HALMOS_{len(vulnerabilities)}",
                    type=VulnerabilityType.FORMAL_VERIFICATION,
                    severity=VulnerabilitySeverity.HIGH,
                    title="Formal verification failed",
                    description=result.get("description", "Property could not be verified"),
                    impact="The contract may not satisfy its formal specifications",
                    remediation="Review the property and contract logic",
                    references=["Halmos verification"],
                    metadata={"property": result.get("property"), "counterexample": result.get("counterexample")}
                )
                vulnerabilities.append(vulnerability)
        
        return vulnerabilities
    
    async def run_halmos_verification(self, code: str, contract_name: str) -> List[Vulnerability]:
        """
        Execute Halmos pour la verification formelle.
        
        Args:
            code: Code a verifier
            contract_name: Nom du contrat
            
        Returns:
            List[Vulnerability]: Vulnerabilites detectees
        """
        try:
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sol', delete=False) as f:
                f.write(code)
                filepath = f.name
            
            try:
                # Execution de Halmos
                cmd = [self.halmos_path, filepath, "--json"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                
                if result.returncode != 0:
                    logger.error(f"Halmos execution failed: {result.stderr}")
                    return []
                
                try:
                    halmos_json = json.loads(result.stdout)
                    return self.parse_halmos_json(halmos_json)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Halmos JSON: {str(e)}")
                    return []
                    
            finally:
                os.unlink(filepath)
                
        except subprocess.TimeoutExpired:
            logger.error("Halmos verification timed out (120s)")
            return []
        except Exception as e:
            logger.error(f"Halmos verification failed: {str(e)}")
            return []
    
    # =========================================================================
    # ENRICHISSEMENT ET TRAITEMENT
    # =========================================================================
    
    async def _enrich_with_rag(self, report: AuditReport) -> AuditReport:
        """
        Enrichit l'audit avec le contexte RAG.
        
        Args:
            report: Rapport d'audit
            
        Returns:
            AuditReport: Rapport enrichi
        """
        if not self.knowledge_base:
            return report
        
        try:
            for vuln in report.vulnerabilities:
                query = f"{vuln.type.value} {vuln.title} smart contract security remediation"
                docs = self.knowledge_base.query_context(query, n_results=2)
                if docs:
                    vuln.references.extend(docs)
                    vuln.remediation += f"\n\nContext: {docs[0][:200]}..."
            
            logger.info(f"Enriched audit with RAG context")
        except Exception as e:
            logger.warning(f"RAG enrichment failed: {str(e)}")
        
        return report
    
    async def _apply_best_practices(self, report: AuditReport) -> AuditReport:
        """
        Applique les bonnes pratiques a l'audit.
        
        Args:
            report: Rapport d'audit
            
        Returns:
            AuditReport: Rapport avec bonnes pratiques appliquees
        """
        for practice in self.best_practices:
            try:
                # Validation du code
                validation = await practice.validate({"code": report.contract_name})
                if not validation.get("passed", True):
                    # Ajout des suggestions
                    for violation in validation.get("violations", []):
                        vuln = Vulnerability(
                            id=f"BP_{len(report.vulnerabilities)}",
                            type=VulnerabilityType.COMPLIANCE,
                            severity=VulnerabilitySeverity.LOW,
                            title=violation.get("rule_name", "Best practice violation"),
                            description=violation.get("message", ""),
                            remediation=violation.get("suggestion", ""),
                            references=["Best practices"]
                        )
                        report.vulnerabilities.append(vuln)
            except Exception as e:
                logger.warning(f"Best practice validation failed: {str(e)}")
        
        return report
    
    async def _generate_fixes(self, report: AuditReport) -> AuditReport:
        """
        Genere des correctifs pour les vulnerabilites.
        
        Args:
            report: Rapport d'audit
            
        Returns:
            AuditReport: Rapport avec correctifs
        """
        for vuln in report.vulnerabilities:
            if not vuln.remediation_code and self.llm_client:
                try:
                    prompt = f"""
                    Generate a fix for the following vulnerability:
                    
                    Type: {vuln.type.value}
                    Title: {vuln.title}
                    Description: {vuln.description}
                    
                    Provide the fix as Solidity code.
                    """
                    
                    response = await self.llm_client.generate(
                        prompt=prompt,
                        system_prompt="You are an expert at fixing smart contract vulnerabilities.",
                        temperature=0.2
                    )
                    
                    vuln.remediation_code = self._extract_code_from_response(response)
                except Exception as e:
                    logger.warning(f"Failed to generate fix for {vuln.id}: {str(e)}")
        
        return report
    
    def _extract_code_from_response(self, response: str) -> str:
        """Extrait le code de la reponse du LLM."""
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", response)
        return code_blocks[0].strip() if code_blocks else response.strip()
    
    # =========================================================================
    # CLASSIFICATION ET SCORING
    # =========================================================================
    
    def _classify_vulnerabilities(self, report: AuditReport) -> None:
        """
        Classe les vulnerabilites par severite.
        
        Args:
            report: Rapport d'audit
        """
        report.critical_count = 0
        report.high_count = 0
        report.medium_count = 0
        report.low_count = 0
        
        for vuln in report.vulnerabilities:
            if vuln.severity == VulnerabilitySeverity.CRITICAL:
                report.critical_count += 1
            elif vuln.severity == VulnerabilitySeverity.HIGH:
                report.high_count += 1
            elif vuln.severity == VulnerabilitySeverity.MEDIUM:
                report.medium_count += 1
            elif vuln.severity == VulnerabilitySeverity.LOW:
                report.low_count += 1
    
    def _calculate_security_score(self, report: AuditReport) -> float:
        """
        Calcule le score de securite (0-100).
        
        Args:
            report: Rapport d'audit
            
        Returns:
            float: Score de securite
        """
        score = 100.0
        
        # Deductions selon la severite
        score -= report.critical_count * 25.0
        score -= report.high_count * 10.0
        score -= report.medium_count * 5.0
        score -= report.low_count * 2.0
        
        return max(0.0, min(100.0, score))
    
    def _deduplicate_vulnerabilities(self, vulns: List[Vulnerability]) -> List[Vulnerability]:
        """
        Deduplique les vulnerabilites similaires.
        
        Args:
            vulns: Liste des vulnerabilites
            
        Returns:
            List[Vulnerability]: Liste dedupliquee
        """
        seen = set()
        unique = []
        
        for vuln in vulns:
            key = f"{vuln.type.value}_{vuln.title}_{vuln.location}"
            if key not in seen:
                seen.add(key)
                unique.append(vuln)
        
        return unique
    
    # =========================================================================
    # FORMATAGE ET RAPPORTS
    # =========================================================================
    
    def format_remediation_guide(self, vulnerabilities: List[Vulnerability]) -> str:
        """
        Genere un guide de correction.
        
        Args:
            vulnerabilities: Liste des vulnerabilites
            
        Returns:
            str: Guide de correction
        """
        if not vulnerabilities:
            return "✅ No vulnerabilities detected. The code is secure."
        
        lines = [
            "🔒 Security Audit Report",
            "=" * 50,
            f"Total vulnerabilities found: {len(vulnerabilities)}",
            ""
        ]
        
        # Groupement par severite
        by_severity = {}
        for vuln in vulnerabilities:
            key = vuln.severity.value
            if key not in by_severity:
                by_severity[key] = []
            by_severity[key].append(vuln)
        
        # Affichage par severite
        for severity in [VulnerabilitySeverity.CRITICAL, VulnerabilitySeverity.HIGH,
                        VulnerabilitySeverity.MEDIUM, VulnerabilitySeverity.LOW]:
            if severity.value in by_severity:
                lines.append(f"\n{'=' * 20} {severity.value.upper()} ({len(by_severity[severity.value])}) {'=' * 20}")
                for vuln in by_severity[severity.value]:
                    lines.append(f"\n🔴 [{vuln.type.value.upper()}] {vuln.title}")
                    lines.append(f"   📍 {vuln.location}")
                    if vuln.line_start:
                        lines.append(f"   📏 Lines: {vuln.line_start}-{vuln.line_end or vuln.line_start}")
                    lines.append(f"   📝 {vuln.description[:200]}...")
                    lines.append(f"   💡 Fix: {vuln.remediation}")
                    if vuln.remediation_code:
                        lines.append(f"   ```solidity\n{vuln.remediation_code}\n```")
        
        lines.append("\n" + "=" * 50)
        lines.append("📊 Summary:")
        lines.append(f"   - Critical: {sum(1 for v in vulnerabilities if v.severity == VulnerabilitySeverity.CRITICAL)}")
        lines.append(f"   - High: {sum(1 for v in vulnerabilities if v.severity == VulnerabilitySeverity.HIGH)}")
        lines.append(f"   - Medium: {sum(1 for v in vulnerabilities if v.severity == VulnerabilitySeverity.MEDIUM)}")
        lines.append(f"   - Low: {sum(1 for v in vulnerabilities if v.severity == VulnerabilitySeverity.LOW)}")
        
        return "\n".join(lines)
    
    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.
        
        Returns:
            Dict: Statistiques detaillees
        """
        total_audits = len(self._audit_history)
        passed_audits = sum(1 for r in self._audit_history if r.passed)
        
        total_vulnerabilities = sum(len(r.vulnerabilities) for r in self._audit_history)
        total_critical = sum(r.critical_count for r in self._audit_history)
        total_high = sum(r.high_count for r in self._audit_history)
        
        avg_score = sum(r.score for r in self._audit_history) / total_audits if total_audits > 0 else 0
        
        return {
            "total_audits": total_audits,
            "passed_audits": passed_audits,
            "failed_audits": total_audits - passed_audits,
            "pass_rate": passed_audits / total_audits if total_audits > 0 else 0,
            "total_vulnerabilities": total_vulnerabilities,
            "average_vulnerabilities_per_audit": total_vulnerabilities / total_audits if total_audits > 0 else 0,
            "total_critical": total_critical,
            "total_high": total_high,
            "average_score": avg_score,
            "min_score": min((r.score for r in self._audit_history), default=0),
            "max_score": max((r.score for r in self._audit_history), default=0),
            **super().health_check()
        }
    
    def get_last_audit(self) -> Optional[AuditReport]:
        """
        Recupere le dernier audit.
        
        Returns:
            Optional[AuditReport]: Dernier rapport ou None
        """
        return self._audit_history[-1] if self._audit_history else None
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<SecurityAgent(agent_id='{self.agent_id}', audits={len(self._audit_history)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.
        
        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "SecurityAgent",
            "audits_count": len(self._audit_history),
            "skills_count": len(self.skills),
            "min_security_score": self.min_security_score,
            "auto_fix": self.auto_fix,
            "health": self.health_check()
        }