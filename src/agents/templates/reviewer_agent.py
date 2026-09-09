# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Reviewer Agent
# ==============================================================================
# Fichier: src/agents/templates/reviewer_agent.py
# Description: Agent critique (Peer-Reviewer) dédié à l'inspection statique
#              du code Solidity. Opère avec une température de 0.0 pour un
#              déterminisme absolu. Bloque les hallucinations avant compilation.
# ==============================================================================

import re
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone
import logging

from src.agents.base.abstract_agent import AbstractAgent
from src.agents.base.skill import BaseSkill
from src.core.status_manager import StatusManager, normalize_status
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.contract_validator import validate_contract, ContractValidator
from src.core.exceptions import PipelineError

# Configuration du logging
logger = logging.getLogger(__name__)


# ==============================================================================
# REVIEWER SKILL
# ==============================================================================

class ReviewerSkill(BaseSkill):
    """
    Compétence spécialisée pour l'analyse syntaxique des contrats.
    Vérifie les imports OpenZeppelin, les cheatcodes Foundry et les bonnes pratiques.
    """
    
    # Liste blanche des imports OpenZeppelin autorisés
    ALLOWED_OZ_IMPORTS = {
        "@openzeppelin/contracts/token/ERC20/ERC20.sol",
        "@openzeppelin/contracts/token/ERC20/extensions/ERC20Burnable.sol",
        "@openzeppelin/contracts/token/ERC20/extensions/ERC20Capped.sol",
        "@openzeppelin/contracts/token/ERC721/ERC721.sol",
        "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol",
        "@openzeppelin/contracts/access/Ownable.sol",
        "@openzeppelin/contracts/access/AccessControl.sol",
        "@openzeppelin/contracts/security/ReentrancyGuard.sol",
        "@openzeppelin/contracts/security/Pausable.sol",
        "@openzeppelin/contracts/utils/math/SafeMath.sol",
        "@openzeppelin/contracts/utils/math/Math.sol",
        "@openzeppelin/contracts/utils/Counters.sol",
        "@openzeppelin/contracts/utils/Strings.sol",
        "@openzeppelin/contracts/proxy/utils/Initializable.sol",
        "@openzeppelin/contracts/proxy/utils/UUPSUpgradeable.sol",
        "@openzeppelin/contracts/interfaces/IERC20.sol",
        "@openzeppelin/contracts/interfaces/IERC721.sol",
    }
    
    # Liste blanche des cheatcodes Foundry standards
    ALLOWED_CHEATCODES = {
        "prank", "startPrank", "stopPrank", "deal", "hoax", "expectRevert",
        "expectEmit", "expectCall", "roll", "warp", "fee", "chainId",
        "store", "load", "etch", "label", "snapshot", "revertTo",
        "record", "accesses", "assume", "skip", "ffi", "breakpoint",
        "broadcast", "startBroadcast", "stopBroadcast", "selectFork",
        "createFork", "createSelectFork", "activeFork", "rollFork",
        "makePersistent", "revokePersistent", "allowCheatcodes"
    }

    def __init__(self, config, **kwargs):
        """
        Initialise la compétence de revue.
        """
        super().__init__(config, **kwargs)
        self.logger = StructuredLogger(f"ReviewerSkill_{self.skill_id}")
        self.logger.set_context(skill_id=self.skill_id)

    async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Exécute l'analyse statique du contrat.
        
        Args:
            params: Doit contenir 'source_code' et optionnellement 'is_test_file'
            
        Returns:
            Dict[str, Any]: Résultat de l'analyse
        """
        source_code = params.get("source_code", "")
        is_test_file = params.get("is_test_file", False)
        
        if not source_code:
            raise ValueError("source_code is required for review")
        
        return self.analyze_smart_contract(source_code, is_test_file)

    def get_system_prompt_rules(self) -> str:
        """
        Retourne les règles système pour le prompt.
        """
        return f"""
        You are a strict code reviewer for Solidity smart contracts.
        
        Rules:
        1. Only allow imports from: {', '.join(sorted(self.ALLOWED_OZ_IMPORTS))}
        2. Only allow cheatcodes: {', '.join(sorted(self.ALLOWED_CHEATCODES))}
        3. Reject any code with hallucinations
        4. Force deterministic output (temperature=0.0)
        
        If any rule is violated, reject the code immediately.
        """

    def analyze_smart_contract(self, source_code: str, is_test_file: bool = False) -> Dict[str, Any]:
        """
        Analyse lexicale et syntaxique ciblée contre les hallucinations de l'IA.
        
        Args:
            source_code: Code source à analyser
            is_test_file: Indique si c'est un fichier de test
            
        Returns:
            Dict[str, Any]: Résultats de l'analyse
        """
        self.logger.log_info(
            "Starting static analysis",
            "analysis_start",
            source_length=len(source_code),
            is_test_file=is_test_file
        )
        
        errors = []
        warnings = []
        suggestions = []
        metrics = {
            "lines_analyzed": len(source_code.splitlines()),
            "imports_checked": 0,
            "hallucinations_detected": 0,
            "cheatcodes_found": 0,
            "oz_imports_found": 0,
        }
        
        # ============================================================
        # 1. Validation de la version Pragma
        # ============================================================
        pragma_match = re.search(r"pragma solidity [><=\^]*(\d+\.\d+\.\d+);", source_code)
        if not pragma_match:
            errors.append("Déclaration 'pragma solidity' manquante ou mal formatée.")
        else:
            version = pragma_match.group(1)
            # Vérifier la version (au moins 0.8.0)
            try:
                major, minor, patch = map(int, version.split('.'))
                if major < 0 or (major == 0 and minor < 8):
                    warnings.append(f"Version Solidity {version} est ancienne. Recommandé: ^0.8.0+")
                else:
                    metrics["pragma_version"] = version
            except ValueError:
                warnings.append(f"Format de version invalide: {version}")
        
        # ============================================================
        # 2. Validation des imports OpenZeppelin
        # ============================================================
        imports = re.findall(r'import\s+["\']([^"\']+)["\'];', source_code)
        metrics["imports_checked"] = len(imports)
        
        for imp in imports:
            if "openzeppelin" in imp.lower():
                metrics["oz_imports_found"] += 1
                if imp not in self.ALLOWED_OZ_IMPORTS:
                    errors.append(f"Import OpenZeppelin halluciné ou non autorisé : {imp}")
                    suggestions.append(f"Remplacer '{imp}' par un import autorisé de la liste blanche")
            elif "forge-std" in imp.lower():
                # Les imports Foundry sont autorisés dans les tests
                if not is_test_file:
                    warnings.append(f"Import Foundry dans un fichier non-test : {imp}")
        
        # ============================================================
        # 3. Vérification des Cheatcodes (si fichier de test)
        # ============================================================
        if is_test_file:
            vm_calls = re.findall(r'vm\.([a-zA-Z0-9_]+)\(', source_code)
            metrics["cheatcodes_found"] = len(vm_calls)
            
            for call in vm_calls:
                if call not in self.ALLOWED_CHEATCODES:
                    errors.append(f"Cheatcode Foundry inexistant ou halluciné : vm.{call}")
                    suggestions.append(f"Remplacer 'vm.{call}' par un cheatcode autorisé: {', '.join(sorted(self.ALLOWED_CHEATCODES)[:5])}...")
        
        # ============================================================
        # 4. Vérification d'héritage avec override
        # ============================================================
        override_pattern = r'\boverride\b'
        inheritance_pattern = r'\bis\s+\w+'
        
        if re.search(override_pattern, source_code):
            if not re.search(inheritance_pattern, source_code):
                warnings.append("Utilisation du mot-clé 'override' détectée sans héritage explicite ('is').")
                suggestions.append("Ajouter un héritage comme 'contract MyContract is BaseContract'")
        
        # ============================================================
        # 5. Détection des patterns d'hallucination courants
        # ============================================================
        hallucination_patterns = [
            (r'import\s+["\']@openzeppelin/contracts/[^"\']+["\'];', "Import OpenZeppelin invalide"),
            (r'function\s+\w+\s*\([^)]*\)\s*(?:public|external)\s*returns\s*\([^)]*\)\s*{\s*}', "Fonction vide (possible hallucination)"),
            (r'require\(\s*[^,]*,\s*["\'][^"\']*["\']\s*\);', "Require avec message (bonne pratique)"),
        ]
        
        for pattern, description in hallucination_patterns:
            matches = re.findall(pattern, source_code, re.DOTALL)
            if matches and len(matches) > 5:  # Trop de correspondances = possible hallucination
                warnings.append(f"Hallucination potentielle détectée: {description} ({len(matches)} occurrences)")
        
        # ============================================================
        # 6. Vérification des bonnes pratiques
        # ============================================================
        # SPDX License Identifier
        if "SPDX-License-Identifier" not in source_code:
            warnings.append("SPDX-License-Identifier manquant")
            suggestions.append("Ajouter '// SPDX-License-Identifier: MIT'")
        
        # Natspec comments
        functions = re.findall(r'function\s+\w+\s*\([^)]*\)\s*(?:public|external|internal|private)', source_code)
        for func in functions[:3]:  # Vérifier les 3 premières fonctions
            if "/**" not in source_code[:source_code.find(func)]:
                # Ne pas alerter sur les fonctions privées
                if "private" not in func:
                    warnings.append(f"Fonction sans documentation Natspec: {func[:50]}...")
                    suggestions.append("Ajouter une documentation Natspec avec @param et @return")
        
        # ============================================================
        # Construction du résultat
        # ============================================================
        metrics["hallucinations_detected"] = len(errors)
        
        # Classification des erreurs
        critical_errors = [e for e in errors if "halluciné" in e or "non autorisé" in e]
        high_errors = [e for e in errors if e not in critical_errors]
        
        result = {
            "passed": len(errors) == 0,
            "critical_errors": critical_errors,
            "high_errors": high_errors,
            "warnings": warnings,
            "suggestions": suggestions,
            "metrics": metrics,
            "validated_code": source_code if len(errors) == 0 else None,
            "requires_human_review": len(critical_errors) > 0 or len(warnings) > 5,
        }
        
        # Logging des résultats
        if len(errors) > 0:
            self.logger.log_warning(
                f"Code review found {len(errors)} errors and {len(warnings)} warnings",
                "review_completed",
                errors_count=len(errors),
                warnings_count=len(warnings),
                critical_errors=len(critical_errors)
            )
        else:
            self.logger.log_info(
                f"Code review passed with {len(warnings)} warnings",
                "review_passed",
                warnings_count=len(warnings)
            )
        
        return result


# ==============================================================================
# REVIEWER AGENT
# ==============================================================================

class ReviewerAgent(AbstractAgent):
    """
    Agent critique (Peer-Reviewer) dédié à l'inspection statique du code Solidity.
    Opère avec une température de 0.0 pour un déterminisme absolu.
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str = "ReviewerAgent",
        skills: Optional[List[BaseSkill]] = None,
        llm_client = None,
        knowledge_base = None,
        max_retries: int = 1,  # Une seule tentative pour un comportement déterministe
        task_timeout: Optional[int] = None,
        log_callback = None,
        **kwargs
    ):
        """
        Initialise l'Agent Reviewer.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (défaut: "ReviewerAgent")
            skills: Liste des compétences (optionnel)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances (optionnel)
            max_retries: Nombre maximum de tentatives (défaut: 1)
            task_timeout: Timeout par tâche (optionnel)
            log_callback: Callback pour la persistance des logs (optionnel)
            **kwargs: Arguments supplémentaires
        """
        super().__init__(
            agent_id=agent_id,
            name=name,
            skills=skills,
            llm_client=llm_client,
            knowledge_base=knowledge_base,
            max_retries=max_retries,
            task_timeout=task_timeout,
            log_callback=log_callback,
            **kwargs
        )
        
        # Forcer la température à 0.0 pour un comportement déterministe
        if self.llm_client:
            self.llm_client.temperature = 0.0
        
        # Ajout du ReviewerSkill par défaut si aucune compétence n'est fournie
        if not skills:
            from src.core.models import SkillConfig
            reviewer_config = SkillConfig(
                skill_id="reviewer_skill",
                name="Code Reviewer",
                description="Analyse statique du code Solidity pour détecter les hallucinations",
                prompt_rules="You are a strict code reviewer. Reject any hallucinations.",
                input_schema={
                    "source_code": {"type": "string", "description": "Code source à analyser"},
                    "is_test_file": {"type": "boolean", "description": "Indique si c'est un fichier de test"}
                }
            )
            reviewer_skill = ReviewerSkill(reviewer_config, llm_client=llm_client)
            self.attach_skill(reviewer_skill)
        
        self.logger = StructuredLogger(f"ReviewerAgent_{agent_id}")
        self.logger.set_context(agent_id=agent_id)
        
        logger.info(f"ReviewerAgent initialized: {agent_id} (temperature=0.0)")

    @validate_contract(required_methods=["execute_task"])
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Point d'entrée principal pour la tâche de révision.
        
        Args:
            task_data: Doit contenir:
                - 'source_code': Code source à analyser
                - 'is_test_file': Booléen (défaut: False)
                - 'task_id': ID de la tâche (optionnel)
                
        Returns:
            Dict[str, Any]: Résultat de la revue
        """
        self.logger.set_context(task_id=task_data.get("task_id", "unknown"))
        self.logger.log_info(
            "Starting review task",
            "review_started",
            source_length=len(task_data.get("source_code", ""))
        )
        
        try:
            # Valider les données d'entrée
            self._validate_task_data(task_data)
            
            # Vérifier que la compétence ReviewerSkill est attachée
            reviewer_skill = self.get_skill("reviewer_skill")
            if not reviewer_skill:
                raise PipelineError("ReviewerSkill not attached to agent")
            
            # Exécuter la compétence
            result = await reviewer_skill.execute_with_validation({
                "source_code": task_data.get("source_code", ""),
                "is_test_file": task_data.get("is_test_file", False)
            }, validate_output=True)
            
            # Extraire les résultats de l'analyse
            analysis_result = result.get("result", {})
            
            if analysis_result.get("passed", False):
                self.logger.log_info(
                    "Code review passed",
                    "review_passed",
                    metrics=analysis_result.get("metrics", {})
                )
                return {
                    "status": "success",
                    "validated_code": analysis_result.get("validated_code"),
                    "metrics": analysis_result.get("metrics", {}),
                    "warnings": analysis_result.get("warnings", []),
                    "suggestions": analysis_result.get("suggestions", [])
                }
            else:
                self.logger.log_warning(
                    "Code review failed",
                    "review_failed",
                    errors=analysis_result.get("critical_errors", []),
                    warnings=analysis_result.get("warnings", [])
                )
                return {
                    "status": "failed",
                    "errors": analysis_result.get("critical_errors", []),
                    "warnings": analysis_result.get("warnings", []),
                    "suggestions": analysis_result.get("suggestions", []),
                    "metrics": analysis_result.get("metrics", {}),
                    "requires_human_review": analysis_result.get("requires_human_review", True)
                }
                
        except Exception as e:
            self.logger.log_error(
                "Review task failed",
                e,
                "review_error",
                task_id=task_data.get("task_id")
            )
            return {
                "status": "failed",
                "error": str(e),
                "errors": [f"Review failed: {str(e)}"]
            }
        finally:
            self.logger.clear_context()

    def _validate_task_data(self, task_data: Dict[str, Any]) -> None:
        """
        Valide les données de la tâche.
        
        Args:
            task_data: Données à valider
            
        Raises:
            ValueError: Si les données sont invalides
        """
        super()._validate_task_data(task_data)
        
        if "source_code" not in task_data:
            raise ValueError("Missing required field: source_code")
        
        if not task_data.get("source_code"):
            raise ValueError("source_code cannot be empty")
    
    def get_review_skill(self) -> Optional[ReviewerSkill]:
        """
        Récupère la compétence de revue.
        
        Returns:
            Optional[ReviewerSkill]: Compétence de revue ou None
        """
        skill = self.get_skill("reviewer_skill")
        if isinstance(skill, ReviewerSkill):
            return skill
        return None


# ==============================================================================
# FONCTION DE CONVENANCE
# ==============================================================================

def create_reviewer_agent(
    agent_id: str,
    llm_client=None,
    knowledge_base=None,
    **kwargs
) -> ReviewerAgent:
    """
    Crée un agent reviewer avec ses dépendances.
    
    Args:
        agent_id: Identifiant unique de l'agent
        llm_client: Client LLM (optionnel)
        knowledge_base: Base de connaissances (optionnel)
        **kwargs: Arguments supplémentaires pour ReviewerAgent
        
    Returns:
        ReviewerAgent: Agent configuré
    """
    return ReviewerAgent(
        agent_id=agent_id,
        llm_client=llm_client,
        knowledge_base=knowledge_base,
        **kwargs
    )


# ==============================================================================
# TEST UNITAIRE (si exécuté directement)
# ==============================================================================

if __name__ == "__main__":
    import asyncio
    
    async def test_reviewer():
        print("=" * 60)
        print("Smart Contract Dev Pipeline 2.0 - Reviewer Agent")
        print("=" * 60)
        
        # Code valide
        valid_code = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

contract MyToken is ERC20, Ownable {
    constructor() ERC20("MyToken", "MTK") {}
    
    function mint(address to, uint256 amount) public onlyOwner {
        _mint(to, amount);
    }
}"""
        
        # Code avec hallucinations
        hallucinated_code = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/token/ERC20/NonExistent.sol";
import "@openzeppelin/contracts/magic/SuperSecure.sol";

contract MyToken is NonExistent {
    function magicFunction() public {
        vm.superMagic();
    }
}"""
        
        # Création de l'agent
        agent = ReviewerAgent(
            agent_id="reviewer_001",
            name="TestReviewer",
            max_retries=1
        )
        
        # Test avec code valide
        print("\n📋 Test avec code valide:")
        result = await agent.execute_task({
            "task_id": "test_001",
            "source_code": valid_code,
            "is_test_file": False
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Errors: {result.get('errors', [])}")
        print(f"  Metrics: {result.get('metrics', {})}")
        
        # Test avec code halluciné
        print("\n📋 Test avec code halluciné:")
        result = await agent.execute_task({
            "task_id": "test_002",
            "source_code": hallucinated_code,
            "is_test_file": False
        })
        print(f"  Status: {result.get('status')}")
        print(f"  Errors: {result.get('errors', [])}")
        print(f"  Warnings: {result.get('warnings', [])}")
        print(f"  Metrics: {result.get('metrics', {})}")
        
        print("\n✅ Tests terminés.")
    
    asyncio.run(test_reviewer())# src/agents/reviewer_agent.py
import re
from typing import Dict, Any, List
from src.core.abstract_agent import AbstractAgent
from src.core.status_manager import StatusManager
from src.core.structured_logger import StructuredLogger
from src.core.contract_validator import validate_contract

class ReviewerAgent(AbstractAgent):
    """
    Agent critique (Peer-Reviewer) dédié à l'inspection statique du code Solidity.
    Opère avec une température de 0.0 pour un déterminisme absolu.
    """

    # Liste blanche des imports OpenZeppelin autorisés pour bloquer les hallucinations
    ALLOWED_OZ_IMPORTS = {
        "@openzeppelin/contracts/token/ERC20/ERC20.sol",
        "@openzeppelin/contracts/token/ERC721/ERC721.sol",
        "@openzeppelin/contracts/access/Ownable.sol",
        "@openzeppelin/contracts/security/ReentrancyGuard.sol",
        "@openzeppelin/contracts/utils/math/SafeMath.sol"
    }

    # Liste blanche des cheatcodes Foundry standards
    ALLOWED_CHEATCODES = {"prank", "startPrank", "stopPrank", "deal", "hoax", "expectRevert", "expectEmit"}

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        # Surcharge de la configuration LLM pour forcer le déterminisme
        self.config["llm_settings"]["temperature"] = 0.0
        self.config["llm_settings"]["repeat_penalty"] = 1.0
        self.logger = StructuredLogger(f"ReviewerAgent-{agent_id}")

    @validate_contract(required_methods=["analyze_smart_contract"])
    async def execute(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Point d'entrée du pipeline pour la tâche de révision."""
        self.logger.set_context(task_id=task_data.get("task_id"))
        self.logger.log_event("review_started", "Début de l'inspection statique du contrat")

        source_code = task_data.get("source_code", "")
        is_test_file = task_data.get("is_test_file", False)

        if not source_code:
            self.logger.log_error("review_failed", ValueError("Code source manquant"))
            return {
                "status": StatusManager.normalize_status("FAILED"),
                "errors": ["Code source manquant dans les données de la tâche."]
            }

        review_results = self.analyze_smart_contract(source_code, is_test_file)

        if review_results["critical_errors"]:
            self.logger.log_event("review_rejected", "Hallucinations détectées", errors=review_results["critical_errors"])
            return {
                "status": StatusManager.normalize_status("FAILED"),
                "errors": review_results["critical_errors"],
                "metrics": review_results["metrics"]
            }

        self.logger.log_event("review_approved", "Code validé pour la compilation")
        return {
            "status": StatusManager.normalize_status("SUCCESS"),
            "validated_code": source_code,
            "metrics": review_results["metrics"]
        }

    def analyze_smart_contract(self, source_code: str, is_test_file: bool) -> Dict[str, Any]:
        """Analyse lexicale et syntaxique ciblée contre les hallucinations de l'IA."""
        errors = []
        
        # 1. Validation de la version Pragma
        pragma_match = re.search(r"pragma solidity [><=\^]*(\d+\.\d+\.\d+);", source_code)
        if not pragma_match:
            errors.append("Déclaration 'pragma solidity' manquante ou mal formatée.")
            
        # 2. Validation des imports OpenZeppelin
        imports = re.findall(r'import\s+["\']([^"\']+)["\'];', source_code)
        for imp in imports:
            if "openzeppelin" in imp and imp not in self.ALLOWED_OZ_IMPORTS:
                errors.append(f"Import OpenZeppelin halluciné ou non autorisé : {imp}")
                
        # 3. Vérification des Cheatcodes (si fichier de test)
        if is_test_file:
            vm_calls = re.findall(r'vm\.([a-zA-Z0-9_]+)\(', source_code)
            for call in vm_calls:
                if call not in self.ALLOWED_CHEATCODES:
                    errors.append(f"Cheatcode Foundry inexistant ou halluciné : vm.{call}")

        # 4. Vérification d'héritage manquant (Ex: override sans virtual/héritage)
        if "override" in source_code and "is " not in source_code:
             errors.append("Utilisation du mot-clé 'override' détectée sans héritage explicite ('is').")

        return {
            "critical_errors": errors,
            "metrics": {
                "lines_analyzed": len(source_code.splitlines()),
                "imports_checked": len(imports),
                "hallucinations_detected": len(errors)
            }
        }