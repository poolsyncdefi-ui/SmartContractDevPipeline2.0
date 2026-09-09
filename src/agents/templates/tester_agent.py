# src/agents/templates/tester_agent.py

"""
Tester agent for the Smart Contract Dev Pipeline.
F24 – src/agents/templates/tester_agent.py

Role Fonctionnel : Agent de test responsable de:
- La génération de tests unitaires (Foundry/Forge)
- La génération de tests d'invariants
- La génération de tests de fuzzing
- L'exécution des tests et l'analyse des résultats
- La génération de rapports de couverture
- La validation des invariants métier
- L'optimisation des tests pour la performance

Cet agent est le garant de la qualité du code avant déploiement.
Version intégrant les nouveaux modules système.
"""
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime, timezone
import logging
import json
import re
import asyncio
import subprocess
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError
from src.core.status_manager import normalize_status, status_manager
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.contract_validator import ContractValidator, validate_contract
from src.core.intelligent_cache import IntelligentCache, CacheStrategy
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase
from src.agents.base.best_practice import BaseBestPractice

# Configuration du logging
logger = logging.getLogger(__name__)


class TestType(str, Enum):
    """
    Types de tests.
    """
    UNIT = "unit"           # Tests unitaires
    INTEGRATION = "integration"  # Tests d'intégration
    INVARIANT = "invariant"      # Tests d'invariants
    FUZZING = "fuzzing"          # Tests de fuzzing
    PROPERTY = "property"        # Tests de propriétés
    COVERAGE = "coverage"        # Tests de couverture
    ALL = "all"                  # Tous les tests


class TestSeverity(str, Enum):
    """
    Sévérité des échecs de test.
    """
    BLOCKING = "blocking"   # Bloquant - doit être corrigé
    CRITICAL = "critical"   # Critique - doit être corrigé
    HIGH = "high"           # Élevé - devrait être corrigé
    MEDIUM = "medium"       # Moyen - peut être corrigé
    LOW = "low"             # Faible - peut être ignoré
    INFO = "info"           # Information


@dataclass
class TestCase:
    """
    Cas de test.

    Attributes:
        name: Nom du test
        description: Description du test
        type: Type de test
        code: Code du test
        expected_result: Résultat attendu
        severity: Sévérité en cas d'échec
        tags: Tags pour le filtrage
        metadata: Métadonnées supplémentaires
    """
    name: str
    description: str = ""
    type: TestType = TestType.UNIT
    code: str = ""
    expected_result: str = ""
    severity: TestSeverity = TestSeverity.HIGH
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TestResult:
    """
    Résultat d'un test.

    Attributes:
        test_name: Nom du test
        passed: Indique si le test est passé
        duration_ms: Durée en millisecondes
        error: Message d'erreur (optionnel)
        stack_trace: Stack trace (optionnel)
        gas_used: Gaz utilisé (optionnel)
        coverage: Couverture (optionnel)
        metadata: Métadonnées supplémentaires
    """
    test_name: str
    passed: bool
    duration_ms: float = 0.0
    error: Optional[str] = None
    stack_trace: Optional[str] = None
    gas_used: Optional[int] = None
    coverage: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convertit le résultat en dictionnaire."""
        return {
            "test_name": self.test_name,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "stack_trace": self.stack_trace[:200] + "..." if self.stack_trace and len(self.stack_trace) > 200 else self.stack_trace,
            "gas_used": self.gas_used,
            "coverage": self.coverage,
            "metadata": self.metadata
        }


@dataclass
class TestSuiteResult:
    """
    Résultat d'une suite de tests.

    Attributes:
        total_tests: Nombre total de tests
        passed_tests: Nombre de tests passés
        failed_tests: Nombre de tests échoués
        skipped_tests: Nombre de tests ignorés
        total_duration_ms: Durée totale en millisecondes
        coverage: Couverture globale
        gas_used: Gaz total utilisé
        results: Résultats individuels
        errors: Erreurs rencontrées
        metadata: Métadonnées supplémentaires
    """
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    total_duration_ms: float = 0.0
    coverage: float = 0.0
    gas_used: int = 0
    results: List[TestResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convertit le résultat en dictionnaire."""
        return {
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "pass_rate": self.passed_tests / self.total_tests if self.total_tests > 0 else 0,
            "total_duration_ms": self.total_duration_ms,
            "coverage": self.coverage,
            "gas_used": self.gas_used,
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
            "metadata": self.metadata
        }


class TesterAgent(AbstractAgent):
    """
    Agent spécialisé dans la génération et l'exécution de tests.

    Attributes:
        llm_client (Optional[LLMClient]): Client LLM pour la génération
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        best_practices (List[BaseBestPractice]): Bonnes pratiques
        foundry_path (str): Chemin vers Foundry (forge)
        coverage_threshold (float): Seuil de couverture minimum
        default_test_type (TestType): Type de test par défaut
        _test_history (List[TestSuiteResult]): Historique des tests
        _cache (IntelligentCache): Cache des tests
        _logger (StructuredLogger): Logger structuré
        _retry_handler (AdaptiveRetry): Système de retry
    """

    # Templates de tests pour différents types de contrats
    TEST_TEMPLATES = {
        "ERC20": """
import "forge-std/Test.sol";
import "../contracts/{contract_name}.sol";

contract {contract_name}Test is Test {{
    {contract_name} public token;
    address public owner = address(0x1);
    address public user = address(0x2);
    uint256 public initialSupply = 1000000 ether;

    function setUp() public {{
        vm.prank(owner);
        token = new {contract_name}();
        token.mint(owner, initialSupply);
    }}

    function testInitialSupply() public {{
        assertEq(token.totalSupply(), initialSupply);
    }}

    function testTransfer() public {{
        uint256 amount = 100 ether;
        vm.prank(owner);
        token.transfer(user, amount);
        assertEq(token.balanceOf(user), amount);
        assertEq(token.balanceOf(owner), initialSupply - amount);
    }}

    function testTransferInsufficientBalance() public {{
        vm.prank(user);
        vm.expectRevert("ERC20: insufficient balance");
        token.transfer(owner, 100 ether);
    }}
}}
""",
        "ERC721": """
import "forge-std/Test.sol";
import "../contracts/{contract_name}.sol";

contract {contract_name}Test is Test {{
    {contract_name} public nft;
    address public owner = address(0x1);
    address public user = address(0x2);
    uint256 public tokenId = 1;

    function setUp() public {{
        vm.prank(owner);
        nft = new {contract_name}();
        nft.mint(owner, tokenId);
    }}

    function testOwnerOf() public {{
        assertEq(nft.ownerOf(tokenId), owner);
    }}

    function testTransferFrom() public {{
        vm.prank(owner);
        nft.transferFrom(owner, user, tokenId);
        assertEq(nft.ownerOf(tokenId), user);
    }}
}}
""",
        "CUSTOM": """
import "forge-std/Test.sol";
import "../contracts/{contract_name}.sol";

contract {contract_name}Test is Test {{
    {contract_name} public contractInstance;
    address public owner = address(0x1);

    function setUp() public {{
        vm.prank(owner);
        contractInstance = new {contract_name}();
    }}

    function testInitialState() public {{
        // Test de l'état initial
        assertTrue(true);
    }}

    function testFunctionality() public {{
        // Test des fonctionnalités
        assertTrue(true);
    }}
}}
"""
    }

    def __init__(
        self,
        agent_id: str,
        name: str = "TesterAgent",
        skills: Optional[List] = None,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        best_practices: Optional[List[BaseBestPractice]] = None,
        foundry_path: str = "forge",
        coverage_threshold: float = 80.0,
        default_test_type: TestType = TestType.ALL,
        cache_enabled: bool = True,
        cache_ttl: int = 3600,
        log_callback=None
    ):
        """
        Initialise l'Agent Tester.

        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (defaut: "TesterAgent")
            skills: Liste des compétences (optionnel)
            llm_client: Client LLM pour la génération
            knowledge_base: Base de connaissances RAG
            best_practices: Bonnes pratiques à appliquer
            foundry_path: Chemin vers Foundry (defaut: "forge")
            coverage_threshold: Seuil de couverture minimum (defaut: 80.0)
            default_test_type: Type de test par défaut (defaut: ALL)
            cache_enabled: Activer le cache
            cache_ttl: Durée de vie du cache en secondes
            log_callback: Callback pour les logs
        """
        super().__init__(
            agent_id=agent_id,
            name=name,
            skills=skills,
            llm_client=llm_client,
            knowledge_base=knowledge_base,
            log_callback=log_callback
        )
        self.llm_client = llm_client
        self.knowledge_base = knowledge_base
        self.best_practices = best_practices or []
        self.foundry_path = foundry_path
        self.coverage_threshold = coverage_threshold
        self.default_test_type = default_test_type
        self._test_history: List[TestSuiteResult] = []

        # Cache intelligent
        self._cache = IntelligentCache(
            default_ttl=cache_ttl,
            max_entries=200,
            strategy=CacheStrategy.ADAPTIVE,
            enable_metrics=True
        )
        if cache_enabled:
            self._cache.start()

        # Logger structuré
        self._logger = StructuredLogger(
            component_name=f"TesterAgent_{agent_id}",
            log_level=LogLevel.INFO
        )
        self._logger.set_context(agent_id=agent_id)

        # Système de retry adaptatif
        self._retry_handler = AdaptiveRetry(
            base_delay=1.0,
            max_delay=30.0,
            max_retries=3,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=True,
            retryable_exceptions=(subprocess.TimeoutExpired, PipelineError)
        )

        logger.info(f"TesterAgent initialized: {agent_id} (coverage_threshold={coverage_threshold}%)")

    @validate_contract(required_methods=["execute_task"])
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute la génération et l'exécution des tests.

        Args:
            task_data: Doit contenir:
                - 'contract_code': Code du contrat
                - 'contract_name': Nom du contrat
                - 'test_type': Type de test (optionnel)
                - 'test_cases': Cas de test personnalisés (optionnel)
                - 'contract_type': Type de contrat (ERC20, ERC721, CUSTOM)

        Returns:
            Dict contenant:
            - 'status': success ou failed
            - 'result': TestSuiteResult en dictionnaire
            - 'tests': Tests générés
            - 'coverage': Couverture
            - 'passed': Booléen indiquant si tous les tests sont passés
        """
        start_time = datetime.now(timezone.utc)
        self._logger.set_context(task_id=task_data.get("task_id", "unknown"))

        try:
            # 1. Extraction des paramètres
            contract_code = task_data.get("contract_code", "")
            contract_name = task_data.get("contract_name", "unknown")
            test_type_str = task_data.get("test_type", self.default_test_type.value)
            custom_test_cases = task_data.get("test_cases", [])
            contract_type = task_data.get("contract_type", "CUSTOM")

            if not contract_code:
                raise ValueError("contract_code is required")

            # 2. Détermination du type de test
            try:
                test_type = TestType(test_type_str.lower())
            except ValueError:
                self._logger.log_warning(
                    f"Invalid test type '{test_type_str}', using default '{self.default_test_type.value}'",
                    "invalid_test_type"
                )
                test_type = self.default_test_type

            # 3. Vérification du cache
            cache_key = f"{contract_name}_{test_type.value}_{hash(contract_code)}"
            cached_result = await self._cache.get(cache_key)
            if cached_result is not None:
                self._logger.log_info("Cache hit for tests", "cache_hit")
                return cached_result

            # 4. Génération des tests
            test_suite = await self._generate_tests(
                contract_code=contract_code,
                contract_name=contract_name,
                test_type=test_type,
                custom_test_cases=custom_test_cases,
                contract_type=contract_type
            )

            # 5. Exécution des tests
            result = await self._execute_tests(
                contract_code=contract_code,
                contract_name=contract_name,
                test_suite=test_suite
            )

            # 6. Analyse des résultats
            result = await self._analyze_test_results(result)

            # 7. Application des bonnes pratiques
            if self.best_practices:
                result = await self._apply_best_practices(result)

            # 8. Persistance du résultat
            self._test_history.append(result)

            # 9. Logging de l'exécution
            await self._log_execution(
                task_data=task_data,
                result={
                    "status": "success",
                    "passed": result.passed_tests == result.total_tests,
                    "coverage": result.coverage,
                    "tests": result.total_tests
                },
                success=True,
                duration=(datetime.now(timezone.utc) - start_time).total_seconds()
            )

            # 10. Mise en cache
            result_dict = {
                "status": "success",
                "result": result.to_dict(),
                "tests": test_suite,
                "coverage": result.coverage,
                "passed": result.passed_tests == result.total_tests,
                "pass_rate": result.passed_tests / result.total_tests if result.total_tests > 0 else 0,
                "metadata": {
                    "execution_time": (datetime.now(timezone.utc) - start_time).total_seconds(),
                    "test_type": test_type.value,
                    "total_tests": result.total_tests,
                    "failed_tests": result.failed_tests
                }
            }

            await self._cache.set(
                cache_key,
                result_dict,
                ttl=3600,
                tags=[contract_name, test_type.value]
            )

            self._logger.log_info(
                f"Test execution completed: {result.passed_tests}/{result.total_tests} passed",
                "tests_completed",
                passed=result.passed_tests,
                total=result.total_tests,
                coverage=result.coverage
            )

            return result_dict

        except Exception as e:
            self._logger.log_error(
                f"Test execution failed: {str(e)}",
                e,
                "tests_failed",
                contract_name=task_data.get("contract_name", "unknown")
            )
            return {
                "status": "failed",
                "error": str(e),
                "execution_time": (datetime.now(timezone.utc) - start_time).total_seconds()
            }
        finally:
            self._logger.clear_context()

    # =========================================================================
    # GÉNÉRATION DE TESTS
    # =========================================================================

    async def _generate_tests(
        self,
        contract_code: str,
        contract_name: str,
        test_type: TestType,
        custom_test_cases: List[Dict],
        contract_type: str
    ) -> List[TestCase]:
        """
        Génère les tests pour le contrat.

        Args:
            contract_code: Code du contrat
            contract_name: Nom du contrat
            test_type: Type de test
            custom_test_cases: Cas de test personnalisés
            contract_type: Type de contrat (ERC20, ERC721, CUSTOM)

        Returns:
            List[TestCase]: Cas de test générés
        """
        self._logger.log_info(
            f"Generating tests for {contract_name}",
            "test_generation_start",
            test_type=test_type.value,
            contract_type=contract_type
        )

        test_cases = []

        # 1. Tests depuis le template
        template_key = contract_type if contract_type in self.TEST_TEMPLATES else "CUSTOM"
        template = self.TEST_TEMPLATES[template_key].format(contract_name=contract_name)

        # 2. Tests personnalisés
        for custom_case in custom_test_cases:
            test_case = TestCase(
                name=custom_case.get("name", "custom_test"),
                description=custom_case.get("description", ""),
                type=TestType(custom_case.get("type", "unit")),
                code=custom_case.get("code", ""),
                expected_result=custom_case.get("expected_result", ""),
                severity=TestSeverity(custom_case.get("severity", "high")),
                tags=custom_case.get("tags", []),
                metadata=custom_case.get("metadata", {})
            )
            test_cases.append(test_case)

        # 3. Génération via LLM (si disponible et si demandé)
        if self.llm_client and test_type in [TestType.UNIT, TestType.ALL, TestType.PROPERTY]:
            llm_tests = await self._generate_tests_with_llm(
                contract_code=contract_code,
                contract_name=contract_name,
                test_type=test_type
            )
            test_cases.extend(llm_tests)

        # 4. Si aucun test n'a été généré, utiliser le template
        if not test_cases:
            test_case = TestCase(
                name=f"{contract_name}_template_test",
                description=f"Template tests for {contract_name}",
                type=TestType.UNIT,
                code=template,
                severity=TestSeverity.CRITICAL,
                tags=["template", "auto_generated"]
            )
            test_cases.append(test_case)

        self._logger.log_info(
            f"Generated {len(test_cases)} test cases",
            "tests_generated",
            count=len(test_cases)
        )

        return test_cases

    async def _generate_tests_with_llm(
        self,
        contract_code: str,
        contract_name: str,
        test_type: TestType
    ) -> List[TestCase]:
        """
        Génère des tests via LLM.

        Args:
            contract_code: Code du contrat
            contract_name: Nom du contrat
            test_type: Type de test

        Returns:
            List[TestCase]: Cas de test générés
        """
        test_cases = []

        try:
            prompt = f"""
            Generate comprehensive tests for the following Solidity smart contract.

            Contract Name: {contract_name}
            Contract Code:
            {contract_code[:2000]}

            Test Type: {test_type.value}

            Requirements:
            1. Use Foundry/Forge testing framework
            2. Test all public functions
            3. Include positive and negative test cases
            4. Add fuzzing tests for invariants
            5. Cover edge cases
            6. Use assertions and cheatcodes
            7. Follow best practices
            8. Include Natspec documentation

            Return the test code only.
            """

            response = await self._retry_handler.execute_with_retry(
                self.llm_client.generate,
                prompt=prompt,
                system_prompt="You are an expert at writing comprehensive tests for smart contracts.",
                temperature=0.3
            )

            code = self._extract_test_code(response)

            if code:
                test_case = TestCase(
                    name=f"{contract_name}_llm_test",
                    description=f"LLM-generated tests for {contract_name}",
                    type=TestType(test_type.value) if test_type != TestType.ALL else TestType.UNIT,
                    code=code,
                    severity=TestSeverity.HIGH,
                    tags=["llm_generated", test_type.value],
                    metadata={"generated_by": "LLM"}
                )
                test_cases.append(test_case)

        except Exception as e:
            self._logger.log_warning(f"LLM test generation failed: {str(e)}", "llm_test_generation_failed")

        return test_cases

    def _extract_test_code(self, response: str) -> str:
        """
        Extrait le code de test de la réponse LLM.

        Args:
            response: Réponse du LLM

        Returns:
            str: Code de test
        """
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", response)
        if code_blocks:
            return code_blocks[0].strip()
        return response.strip()

    # =========================================================================
    # EXÉCUTION DES TESTS
    # =========================================================================

    async def _execute_tests(
        self,
        contract_code: str,
        contract_name: str,
        test_suite: List[TestCase]
    ) -> TestSuiteResult:
        """
        Exécute les tests via Foundry.

        Args:
            contract_code: Code du contrat
            contract_name: Nom du contrat
            test_suite: Suite de tests

        Returns:
            TestSuiteResult: Résultat des tests
        """
        self._logger.log_info(
            f"Executing tests for {contract_name}",
            "test_execution_start",
            test_count=len(test_suite)
        )

        try:
            import tempfile
            import os
            import shutil

            temp_dir = tempfile.mkdtemp(prefix="test_")

            try:
                # Création de la structure
                contracts_dir = os.path.join(temp_dir, "contracts")
                test_dir = os.path.join(temp_dir, "test")
                os.makedirs(contracts_dir, exist_ok=True)
                os.makedirs(test_dir, exist_ok=True)

                # Écriture du contrat
                contract_path = os.path.join(contracts_dir, f"{contract_name}.sol")
                with open(contract_path, 'w') as f:
                    f.write(contract_code)

                # Écriture des tests
                results = []
                total_duration = 0.0
                passed = 0
                failed = 0

                for i, test in enumerate(test_suite):
                    test_path = os.path.join(test_dir, f"{test.name}.t.sol")
                    with open(test_path, 'w') as f:
                        f.write(test.code)

                    # Exécution du test individuel
                    test_result = await self._run_single_test(
                        temp_dir,
                        test.name,
                        test
                    )

                    results.append(test_result)
                    total_duration += test_result.duration_ms

                    if test_result.passed:
                        passed += 1
                    else:
                        failed += 1

                # Calcul de la couverture
                coverage = await self._calculate_coverage(temp_dir)

                return TestSuiteResult(
                    total_tests=len(test_suite),
                    passed_tests=passed,
                    failed_tests=failed,
                    total_duration_ms=total_duration,
                    coverage=coverage,
                    results=results
                )

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

        except Exception as e:
            self._logger.log_error(
                f"Test execution failed: {str(e)}",
                e,
                "test_execution_failed"
            )
            return TestSuiteResult(
                errors=[f"Test execution failed: {str(e)}"]
            )

    async def _run_single_test(
        self,
        temp_dir: str,
        test_name: str,
        test_case: TestCase
    ) -> TestResult:
        """
        Exécute un test individuel.

        Args:
            temp_dir: Répertoire temporaire
            test_name: Nom du test
            test_case: Cas de test

        Returns:
            TestResult: Résultat du test
        """
        start_time = datetime.now(timezone.utc)

        try:
            cmd = [
                self.foundry_path,
                "test",
                "--root", temp_dir,
                "--match-test", test_name,
                "-vv"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp_dir
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return TestResult(
                    test_name=test_name,
                    passed=False,
                    duration_ms=30000,
                    error="Test timed out (30s)"
                )

            output = stdout.decode('utf-8', errors='ignore')
            error = stderr.decode('utf-8', errors='ignore')

            duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

            # Analyse du résultat
            passed = "OK" in output and "FAIL" not in output and "Failing" not in output

            # Extraction du gaz utilisé
            gas_match = re.search(r"gas used: (\d+)", output)
            gas_used = int(gas_match.group(1)) if gas_match else None

            return TestResult(
                test_name=test_name,
                passed=passed,
                duration_ms=duration_ms,
                error=error if not passed else None,
                stack_trace=output if not passed else None,
                gas_used=gas_used
            )

        except Exception as e:
            return TestResult(
                test_name=test_name,
                passed=False,
                duration_ms=(datetime.now(timezone.utc) - start_time).total_seconds() * 1000,
                error=str(e)
            )

    async def _calculate_coverage(self, temp_dir: str) -> float:
        """
        Calcule la couverture des tests.

        Args:
            temp_dir: Répertoire temporaire

        Returns:
            float: Couverture en pourcentage
        """
        try:
            cmd = [
                self.foundry_path,
                "coverage",
                "--root", temp_dir,
                "--report", "summary"
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=temp_dir
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=30
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return 0.0

            output = stdout.decode('utf-8', errors='ignore')

            # Extraction du pourcentage de couverture
            match = re.search(r"(\d+\.?\d*)%", output)
            if match:
                return float(match.group(1))

            return 0.0

        except Exception as e:
            self._logger.log_warning(f"Coverage calculation failed: {str(e)}", "coverage_failed")
            return 0.0

    # =========================================================================
    # ANALYSE DES RÉSULTATS
    # =========================================================================

    async def _analyze_test_results(self, result: TestSuiteResult) -> TestSuiteResult:
        """
        Analyse les résultats des tests.

        Args:
            result: Résultat des tests

        Returns:
            TestSuiteResult: Résultat analysé
        """
        self._logger.log_info(
            f"Analyzing test results",
            "test_analysis_start",
            total=result.total_tests,
            passed=result.passed_tests,
            failed=result.failed_tests,
            coverage=result.coverage
        )

        # Vérification des échecs
        failed_tests = [r for r in result.results if not r.passed]
        if failed_tests:
            self._logger.log_warning(
                f"Found {len(failed_tests)} failed tests",
                "test_failures_detected",
                count=len(failed_tests)
            )

        # Vérification de la couverture
        if result.coverage < self.coverage_threshold:
            self._logger.log_warning(
                f"Coverage {result.coverage}% is below threshold {self.coverage_threshold}%",
                "coverage_below_threshold",
                coverage=result.coverage,
                threshold=self.coverage_threshold
            )

        return result

    async def _apply_best_practices(self, result: TestSuiteResult) -> TestSuiteResult:
        """
        Applique les bonnes pratiques.

        Args:
            result: Résultat des tests

        Returns:
            TestSuiteResult: Résultat enrichi
        """
        # Suggestions basées sur les résultats
        suggestions = []

        if result.coverage < self.coverage_threshold:
            suggestions.append(f"Improve test coverage to reach {self.coverage_threshold}%")

        if result.failed_tests > 0:
            suggestions.append(f"Fix {result.failed_tests} failing tests")

        if result.metadata is None:
            result.metadata = {}

        result.metadata["suggestions"] = suggestions

        return result

    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.

        Returns:
            Dict: Statistiques detaillees
        """
        total_test_suites = len(self._test_history)
        total_tests = sum(s.total_tests for s in self._test_history)
        total_passed = sum(s.passed_tests for s in self._test_history)
        total_failed = sum(s.failed_tests for s in self._test_history)

        avg_coverage = sum(s.coverage for s in self._test_history) / total_test_suites if total_test_suites > 0 else 0

        cache_metrics = self._cache.get_metrics()

        return {
            "total_test_suites": total_test_suites,
            "total_tests": total_tests,
            "total_passed": total_passed,
            "total_failed": total_failed,
            "overall_pass_rate": total_passed / total_tests if total_tests > 0 else 0,
            "average_coverage": avg_coverage,
            "coverage_threshold": self.coverage_threshold,
            "default_test_type": self.default_test_type.value,
            "cache_metrics": cache_metrics
        }

    def get_last_test_result(self) -> Optional[TestSuiteResult]:
        """
        Recupere le dernier résultat de test.

        Returns:
            Optional[TestSuiteResult]: Dernier résultat
        """
        return self._test_history[-1] if self._test_history else None

    # =========================================================================
    # REPRESENTATION
    # =========================================================================

    def __repr__(self) -> str:
        return f"<TesterAgent(agent_id='{self.agent_id}', test_suites={len(self._test_history)})>"

    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.

        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "TesterAgent",
            "test_suites_count": len(self._test_history),
            "skills_count": len(self.skills),
            "coverage_threshold": self.coverage_threshold,
            "default_test_type": self.default_test_type.value,
            "cache_metrics": self._cache.get_metrics(),
            "health": self.health_check()
        }


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio

    async def test_tester():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Tester Agent")
        print("=" * 60)

        # Code de test
        contract_code = """
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Counter {
    uint256 public count;

    event Increment(uint256 newCount);

    function increment() public {
        count += 1;
        emit Increment(count);
    }

    function decrement() public {
        require(count > 0, "Counter: count underflow");
        count -= 1;
    }
}
"""

        # Création de l'agent
        agent = TesterAgent(
            agent_id="tester_001",
            name="TestTester",
            coverage_threshold=70.0
        )

        # Test de génération et exécution
        print("\n📋 Test de génération de tests:")
        result = await agent.execute_task({
            "task_id": "test_001",
            "contract_code": contract_code,
            "contract_name": "Counter",
            "contract_type": "CUSTOM",
            "test_type": "unit"
        })

        print(f"  Status: {result.get('status')}")
        print(f"  Pass Rate: {result.get('pass_rate', 0) * 100:.1f}%")
        print(f"  Coverage: {result.get('coverage', 0):.1f}%")
        print(f"  Tests: {result.get('metadata', {}).get('total_tests', 0)}")
        print(f"  Failed: {result.get('metadata', {}).get('failed_tests', 0)}")

        # Statistiques
        print("\n📋 Statistiques:")
        stats = agent.get_statistics()
        for key, value in stats.items():
            if key == "cache_metrics":
                print(f"  {key}: {value}")
            else:
                print(f"  {key}: {value}")

        print("\n✅ Tests terminés.")

    asyncio.run(test_tester())