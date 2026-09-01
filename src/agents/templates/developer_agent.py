# src/agents/templates/developer_agent.py

"""
Developer agent for the Smart Contract Dev Pipeline.
F20 – src/agents/templates/developer_agent.py

Rôle Fonctionnel : Agent developpeur generant le code Solidity et les tests.
L'Agent Developpeur est responsable de:
- La generation de code Solidity a partir de specifications
- La generation de tests unitaires (Foundry/Forge)
- L'auto-correction du code en cas d'erreurs de compilation
- L'optimisation du code pour le gas
- L'application des bonnes pratiques de developpement
- La documentation du code (Natspec)

Cet agent utilise les competences du registre pour generer
du code de qualite, securise et optimise.
"""
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Tuple, Set
from datetime import datetime
import logging
import re
import json
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError
from src.core.models import Skill
from src.agents.base.best_practice import BaseBestPractice, ValidationResult
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase

# Configuration du logging
logger = logging.getLogger(__name__)


class GenerationMode(str, Enum):
    """
    Modes de generation de code.
    """
    INITIAL = "initial"          # Generation initiale
    AUTO_FIX = "auto_fix"        # Correction automatique
    OPTIMIZATION = "optimization" # Optimisation gas
    REFACTOR = "refactor"        # Refactoring
    DOCUMENTATION = "documentation" # Ajout de documentation


class Language(str, Enum):
    """
    Langages de programmation supportes.
    """
    SOLIDITY = "solidity"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    PYTHON = "python"
    RUST = "rust"


@dataclass
class GenerationResult:
    """
    Resultat de la generation de code.
    
    Attributes:
        code (str): Code genere
        tests (Optional[str]): Tests generes
        documentation (Optional[str]): Documentation
        metadata (Dict): Metadonnees
        errors (List[str]): Erreurs rencontrees
        warnings (List[str]): Avertissements
        suggestions (List[str]): Suggestions d'amelioration
        gas_estimate (Optional[int]): Estimation du gas
        security_score (Optional[float]): Score de securite (0-100)
        quality_score (Optional[float]): Score de qualite (0-100)
        generated_at (datetime): Date de generation
    """
    code: str = ""
    tests: Optional[str] = None
    documentation: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    gas_estimate: Optional[int] = None
    security_score: Optional[float] = None
    quality_score: Optional[float] = None
    generated_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict:
        """Convertit le resultat en dictionnaire."""
        return {
            "code": self.code,
            "tests": self.tests,
            "documentation": self.documentation,
            "metadata": self.metadata,
            "errors": self.errors,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "gas_estimate": self.gas_estimate,
            "security_score": self.security_score,
            "quality_score": self.quality_score,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None
        }


class DeveloperAgent(AbstractAgent):
    """
    Agent specialise dans le developpement de smart contracts.
    
    L'DeveloperAgent genere du code Solidity, des tests et
    assure l'auto-correction en cas d'erreurs de compilation.
    
    Attributes:
        llm_client (Optional[LLMClient]): Client LLM pour la generation
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        best_practices (List[BaseBestPractice]): Bonnes pratiques a appliquer
        language (Language): Langage de programmation
        max_retries (int): Nombre maximum de tentatives d'auto-correction
        optimize_gas (bool): Optimiser le gas
        generate_tests (bool): Generer les tests
        generate_documentation (bool): Generer la documentation
        _generation_history (List[GenerationResult]): Historique des generations
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str = "DeveloperAgent",
        skills: Optional[List] = None,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        best_practices: Optional[List[BaseBestPractice]] = None,
        language: Language = Language.SOLIDITY,
        max_retries: int = 3,
        optimize_gas: bool = True,
        generate_tests: bool = True,
        generate_documentation: bool = True,
        max_code_length: int = 5000
    ):
        """
        Initialise l'Agent Developpeur.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent
            skills: Liste des competences (optionnel)
            llm_client: Client LLM pour la generation
            knowledge_base: Base de connaissances RAG
            best_practices: Bonnes pratiques a appliquer
            language: Langage de programmation
            max_retries: Nombre maximum de tentatives d'auto-correction
            optimize_gas: Optimiser le gas (defaut: True)
            generate_tests: Generer les tests (defaut: True)
            generate_documentation: Generer la documentation (defaut: True)
            max_code_length: Longueur maximale du code (defaut: 5000)
        """
        super().__init__(agent_id=agent_id, name=name, skills=skills, llm_client=llm_client)
        self.knowledge_base = knowledge_base
        self.best_practices = best_practices or []
        self.language = language
        self.max_retries = max_retries
        self.optimize_gas = optimize_gas
        self.generate_tests = generate_tests
        self.generate_documentation = generate_documentation
        self.max_code_length = max_code_length
        self._generation_history: List[GenerationResult] = []
        self._compilation_cache: Dict[str, Dict] = {}
        
        logger.info(f"DeveloperAgent initialized: {agent_id} (language={language.value})")
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute la tache de developpement.
        
        Args:
            task_data: Doit contenir:
                - 'mode': Mode de generation (initial, auto_fix, optimization, refactor, documentation)
                - 'spec': Specification pour la generation
                - 'code': Code existant (pour auto_fix, optimization, refactor)
                - 'compiler_errors': Erreurs de compilation (pour auto_fix)
                - 'language': Langage de programmation (optionnel)
                
        Returns:
            Dict contenant:
            - 'status': SUCCESS ou FAILED
            - 'result': GenerationResult en dictionnaire
            - 'code': Code genere
            - 'tests': Tests generes (si applicable)
            - 'documentation': Documentation (si applicable)
        """
        start_time = datetime.utcnow()
        
        try:
            # 1. Extraction des parametres
            mode = GenerationMode(task_data.get("mode", "initial"))
            spec = task_data.get("spec", {})
            existing_code = task_data.get("code", "")
            compiler_errors = task_data.get("compiler_errors", "")
            language = task_data.get("language", self.language.value)
            language_enum = Language(language)
            
            # 2. Generation du code selon le mode
            result = await self._generate_by_mode(
                mode=mode,
                spec=spec,
                existing_code=existing_code,
                compiler_errors=compiler_errors,
                language=language_enum
            )
            
            # 3. Application des bonnes pratiques
            if self.best_practices and result.code:
                result = await self._apply_best_practices(result)
            
            # 4. Validation du code
            if result.code:
                validation = await self._validate_code(result.code, language_enum)
                result.errors.extend(validation.get("errors", []))
                result.warnings.extend(validation.get("warnings", []))
                result.suggestions.extend(validation.get("suggestions", []))
            
            # 5. Logging de l'execution
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),
                prompt=f"Mode: {mode.value}, Language: {language_enum.value}",
                response=f"Generated {len(result.code)} chars",
                tool_output=json.dumps(result.to_dict(), indent=2)[:500]
            )
            
            # 6. Persistance du resultat
            self._generation_history.append(result)
            
            logger.info(f"DeveloperAgent completed: mode={mode.value}, code_length={len(result.code)}")
            
            return {
                "status": "SUCCESS",
                "result": result.to_dict(),
                "code": result.code,
                "tests": result.tests,
                "documentation": result.documentation,
                "metadata": {
                    "mode": mode.value,
                    "language": language_enum.value,
                    "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                    "errors_count": len(result.errors),
                    "warnings_count": len(result.warnings)
                }
            }
            
        except Exception as e:
            logger.error(f"DeveloperAgent execution failed: {str(e)}")
            return {
                "status": "FAILED",
                "error": str(e),
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }
    
    # =========================================================================
    # GENERATION PAR MODE
    # =========================================================================
    
    async def _generate_by_mode(
        self,
        mode: GenerationMode,
        spec: Dict[str, Any],
        existing_code: str,
        compiler_errors: str,
        language: Language
    ) -> GenerationResult:
        """
        Genere du code selon le mode specifie.
        
        Args:
            mode: Mode de generation
            spec: Specification
            existing_code: Code existant
            compiler_errors: Erreurs de compilation
            language: Langage de programmation
            
        Returns:
            GenerationResult: Resultat de la generation
        """
        if mode == GenerationMode.INITIAL:
            return await self.generate_contract_code(spec, language)
        
        elif mode == GenerationMode.AUTO_FIX:
            if not existing_code:
                raise ValueError("Existing code required for auto_fix mode")
            if not compiler_errors:
                logger.warning("No compiler errors provided for auto_fix mode")
            return await self.apply_auto_fix(existing_code, compiler_errors, language)
        
        elif mode == GenerationMode.OPTIMIZATION:
            if not existing_code:
                raise ValueError("Existing code required for optimization mode")
            return await self.optimize_gas_code(existing_code, language)
        
        elif mode == GenerationMode.REFACTOR:
            if not existing_code:
                raise ValueError("Existing code required for refactor mode")
            return await self.refactor_code(existing_code, spec, language)
        
        elif mode == GenerationMode.DOCUMENTATION:
            if not existing_code:
                raise ValueError("Existing code required for documentation mode")
            return await self.generate_documentation_code(existing_code, language)
        
        else:
            raise ValueError(f"Unsupported generation mode: {mode}")
    
    # =========================================================================
    # GENERATION DE CODE
    # =========================================================================
    
    async def generate_contract_code(
        self,
        spec: Dict[str, Any],
        language: Language = Language.SOLIDITY
    ) -> GenerationResult:
        """
        Genere le code du contrat.
        
        Args:
            spec: Specification du contrat
            language: Langage de programmation
            
        Returns:
            GenerationResult: Resultat de la generation
        """
        logger.info(f"Generating contract code for language: {language.value}")
        
        # Preparation du contexte RAG
        context = ""
        if self.knowledge_base:
            try:
                query = f"{spec.get('name', '')} {spec.get('type', '')} smart contract {language.value}"
                docs = self.knowledge_base.query_context(query, n_results=3)
                if docs:
                    context = "\n".join(docs[:3])
                    logger.debug(f"RAG context added ({len(docs)} docs)")
            except Exception as e:
                logger.warning(f"RAG query failed: {str(e)}")
        
        # Construction du prompt
        prompt = self._build_generation_prompt(spec, context, language)
        
        # Generation via LLM
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=self._get_system_prompt(language),
                    temperature=0.4
                )
                code = self._extract_code_from_response(response, language)
            else:
                # Fallback: code template
                code = self._generate_template(spec, language)
            
            # Generation des tests
            tests = None
            if self.generate_tests and code:
                tests = await self.generate_test_suite(code, language)
            
            # Generation de la documentation
            documentation = None
            if self.generate_documentation and code:
                documentation = await self.generate_documentation_code(code, language)
            
            return GenerationResult(
                code=code,
                tests=tests,
                documentation=documentation,
                metadata={"spec": spec, "language": language.value}
            )
            
        except LLMError as e:
            logger.error(f"LLM generation failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Code generation failed: {str(e)}")
            raise
    
    async def generate_test_suite(
        self,
        contract_code: str,
        language: Language = Language.SOLIDITY
    ) -> str:
        """
        Genere les tests pour le contrat.
        
        Args:
            contract_code: Code du contrat
            language: Langage de programmation
            
        Returns:
            str: Code des tests
        """
        logger.info(f"Generating test suite for language: {language.value}")
        
        # Preparation du prompt
        prompt = f"""
        Generate a comprehensive test suite for the following {language.value} smart contract.
        
        Contract Code:
        {contract_code[:2000]}
        
        Requirements:
        1. Use the appropriate testing framework for {language.value}
        2. Test all public functions
        3. Test edge cases and error conditions
        4. Include positive and negative test cases
        5. Add meaningful assertions
        6. Follow best practices for testing
        """
        
        # Generation via LLM
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=f"You are an expert at writing tests for {language.value} smart contracts.",
                    temperature=0.3
                )
                tests = self._extract_code_from_response(response, language)
            else:
                # Fallback: template de tests
                tests = self._generate_test_template(language)
            
            return tests
            
        except Exception as e:
            logger.error(f"Test generation failed: {str(e)}")
            return f"// Test generation failed: {str(e)}"
    
    async def generate_documentation_code(
        self,
        code: str,
        language: Language = Language.SOLIDITY
    ) -> str:
        """
        Genere la documentation pour le code.
        
        Args:
            code: Code a documenter
            language: Langage de programmation
            
        Returns:
            str: Documentation
        """
        logger.info(f"Generating documentation for language: {language.value}")
        
        # Preparation du prompt
        prompt = f"""
        Generate comprehensive documentation for the following {language.value} code.
        
        Code:
        {code[:2000]}
        
        Requirements:
        1. Use {language.value} documentation standards
        2. Document all functions and their parameters
        3. Document return values
        4. Add usage examples if applicable
        5. Document security considerations
        6. Include Natspec or equivalent
        """
        
        # Generation via LLM
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=f"You are an expert at documenting {language.value} code.",
                    temperature=0.3
                )
                return self._extract_code_from_response(response, language)
            else:
                return "// Documentation generation not available"
                
        except Exception as e:
            logger.error(f"Documentation generation failed: {str(e)}")
            return f"// Documentation generation failed: {str(e)}"
    
    async def apply_auto_fix(
        self,
        code: str,
        compiler_errors: str,
        language: Language = Language.SOLIDITY
    ) -> GenerationResult:
        """
        Applique une correction automatique du code.
        
        Args:
            code: Code a corriger
            compiler_errors: Erreurs de compilation
            language: Langage de programmation
            
        Returns:
            GenerationResult: Resultat de la correction
        """
        logger.info(f"Applying auto-fix for language: {language.value}")
        
        # Analyse des erreurs
        error_analysis = self._analyze_compiler_errors(compiler_errors, language)
        
        # Construction du prompt de correction
        prompt = f"""
        Fix the following {language.value} code that has compilation errors.
        
        Errors:
        {compiler_errors}
        
        Error Analysis:
        {json.dumps(error_analysis, indent=2)}
        
        Code to Fix:
        {code}
        
        Requirements:
        1. Fix all compilation errors
        2. Preserve the original functionality
        3. Follow {language.value} best practices
        4. Maintain code quality
        5. Do not introduce new errors
        """
        
        # Tentatives de correction (avec retry)
        fixed_code = code
        all_errors = []
        
        for attempt in range(self.max_retries):
            try:
                if self.llm_client:
                    response = await self.llm_client.generate(
                        prompt=prompt,
                        system_prompt=f"You are an expert at fixing {language.value} compilation errors.",
                        temperature=0.2
                    )
                    fixed_code = self._extract_code_from_response(response, language)
                    
                    # Verification de la correction
                    validation = await self._validate_code(fixed_code, language)
                    if not validation.get("errors"):
                        logger.info(f"Auto-fix successful on attempt {attempt + 1}")
                        break
                    else:
                        all_errors.extend(validation.get("errors", []))
                        # Ajout des erreurs restantes au prompt
                        prompt += f"\n\nRemaining errors:\n{json.dumps(validation.get('errors', []), indent=2)}"
                else:
                    # Fallback: correction basique
                    fixed_code = self._apply_basic_fixes(code, compiler_errors, language)
                    break
                    
            except Exception as e:
                logger.warning(f"Auto-fix attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
        
        # Generation des tests si necessaire
        tests = None
        if self.generate_tests and fixed_code:
            tests = await self.generate_test_suite(fixed_code, language)
        
        return GenerationResult(
            code=fixed_code,
            tests=tests,
            errors=all_errors,
            metadata={"original_code": code, "compiler_errors": compiler_errors}
        )
    
    async def optimize_gas_code(
        self,
        code: str,
        language: Language = Language.SOLIDITY
    ) -> GenerationResult:
        """
        Optimise le code pour le gas.
        
        Args:
            code: Code a optimiser
            language: Langage de programmation
            
        Returns:
            GenerationResult: Resultat de l'optimisation
        """
        logger.info(f"Optimizing code for gas: {language.value}")
        
        # Analyse du code pour identifier les optimisations
        analysis = self._analyze_gas_usage(code, language)
        
        prompt = f"""
        Optimize the following {language.value} code for gas efficiency.
        
        Current Gas Analysis:
        {json.dumps(analysis, indent=2)}
        
        Code to Optimize:
        {code}
        
        Optimization Goals:
        1. Reduce gas costs
        2. Optimize storage usage
        3. Use efficient data types
        4. Minimize external calls
        5. Apply known gas optimization patterns
        
        Keep the functionality identical.
        """
        
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=f"You are an expert at optimizing {language.value} code for gas efficiency.",
                    temperature=0.3
                )
                optimized_code = self._extract_code_from_response(response, language)
            else:
                optimized_code = self._apply_basic_gas_optimizations(code, language)
            
            return GenerationResult(
                code=optimized_code,
                metadata={"original_code": code, "gas_analysis": analysis}
            )
            
        except Exception as e:
            logger.error(f"Gas optimization failed: {str(e)}")
            return GenerationResult(code=code, errors=[str(e)])
    
    async def refactor_code(
        self,
        code: str,
        spec: Dict[str, Any],
        language: Language = Language.SOLIDITY
    ) -> GenerationResult:
        """
        Refactoring du code.
        
        Args:
            code: Code a refactoriser
            spec: Specifications du refactoring
            language: Langage de programmation
            
        Returns:
            GenerationResult: Resultat du refactoring
        """
        logger.info(f"Refactoring code: {language.value}")
        
        prompt = f"""
        Refactor the following {language.value} code according to the specifications.
        
        Specifications:
        {json.dumps(spec, indent=2)}
        
        Code to Refactor:
        {code}
        
        Refactoring Goals:
        1. Improve code structure
        2. Apply design patterns
        3. Improve readability
        4. Reduce duplication
        5. Improve maintainability
        """
        
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt=f"You are an expert at refactoring {language.value} code.",
                    temperature=0.3
                )
                refactored_code = self._extract_code_from_response(response, language)
            else:
                refactored_code = code
            
            return GenerationResult(
                code=refactored_code,
                metadata={"original_code": code, "spec": spec}
            )
            
        except Exception as e:
            logger.error(f"Refactoring failed: {str(e)}")
            return GenerationResult(code=code, errors=[str(e)])
    
    # =========================================================================
    # VALIDATION ET BONNES PRATIQUES
    # =========================================================================
    
    async def _apply_best_practices(self, result: GenerationResult) -> GenerationResult:
        """
        Applique les bonnes pratiques au code.
        
        Args:
            result: Resultat de generation
            
        Returns:
            GenerationResult: Resultat ameliore
        """
        for practice in self.best_practices:
            try:
                validation = await practice.validate({"code": result.code})
                if not validation.get("passed", True):
                    # Application des corrections suggerees
                    for violation in validation.get("violations", []):
                        suggestion = violation.get("suggestion")
                        if suggestion:
                            result.suggestions.append(suggestion)
                    result.warnings.extend(validation.get("warnings", []))
                    
                    # Mise a jour des scores
                    result.quality_score = validation.get("score", 0)
                    result.security_score = validation.get("security_score", 0)
                    
                    # Si des corrections sont disponibles, les appliquer
                    if self.llm_client and validation.get("violations"):
                        fixed_code = await self._apply_fixes_from_validation(result.code, validation)
                        if fixed_code:
                            result.code = fixed_code
                            
            except Exception as e:
                logger.warning(f"Best practice validation failed: {str(e)}")
        
        return result
    
    async def _validate_code(
        self,
        code: str,
        language: Language
    ) -> Dict[str, Any]:
        """
        Valide le code genere.
        
        Args:
            code: Code a valider
            language: Langage de programmation
            
        Returns:
            Dict: Resultats de validation
        """
        validation_result = {
            "errors": [],
            "warnings": [],
            "suggestions": [],
            "passed": True
        }
        
        # Validation basique
        if not code or len(code.strip()) == 0:
            validation_result["errors"].append("Empty code")
            validation_result["passed"] = False
            return validation_result
        
        # Validation de la longueur
        if len(code) > self.max_code_length:
            validation_result["warnings"].append(
                f"Code exceeds maximum length ({len(code)} > {self.max_code_length})"
            )
        
        # Validation specifique au langage
        if language == Language.SOLIDITY:
            validation_result.update(self._validate_solidity_code(code))
        elif language == Language.JAVASCRIPT:
            validation_result.update(self._validate_javascript_code(code))
        elif language == Language.TYPESCRIPT:
            validation_result.update(self._validate_typescript_code(code))
        
        validation_result["passed"] = len(validation_result["errors"]) == 0
        
        return validation_result
    
    def _validate_solidity_code(self, code: str) -> Dict[str, Any]:
        """
        Valide le code Solidity.
        
        Args:
            code: Code Solidity
            
        Returns:
            Dict: Resultats de validation
        """
        result = {"errors": [], "warnings": [], "suggestions": []}
        
        # Verifier la presence de la license
        if "SPDX-License-Identifier" not in code:
            result["warnings"].append("Missing SPDX-License-Identifier")
            result["suggestions"].append("Add '// SPDX-License-Identifier: MIT'")
        
        # Verifier le pragma
        if "pragma solidity" not in code:
            result["errors"].append("Missing pragma solidity statement")
        elif "pragma solidity ^0.8" not in code:
            result["warnings"].append("Consider using Solidity 0.8+ for built-in overflow checks")
        
        # Verifier la presence de contracts
        if "contract" not in code and "interface" not in code and "library" not in code:
            result["warnings"].append("No contract, interface, or library defined")
        
        # Verifier les fonctions sans visibilite
        functions = re.findall(r"function\s+\w+\s*\([^)]*\)\s*(?:public|external|internal|private)?\s*{", code)
        for func in functions:
            if "public" not in func and "external" not in func and "internal" not in func and "private" not in func:
                result["warnings"].append(f"Function lacks explicit visibility: {func[:50]}...")
                result["suggestions"].append("Add explicit visibility (public, external, internal, private)")
        
        return result
    
    def _validate_javascript_code(self, code: str) -> Dict[str, Any]:
        """Valide le code JavaScript."""
        result = {"errors": [], "warnings": [], "suggestions": []}
        
        # Detection de l'utilisation de var
        if re.search(r"\bvar\s+", code):
            result["warnings"].append("Use 'const' or 'let' instead of 'var'")
            result["suggestions"].append("Replace 'var' with 'const' or 'let'")
        
        # Detection des callback sans async/await
        if re.search(r"\.then\s*\(", code):
            result["suggestions"].append("Consider using async/await instead of .then()")
        
        return result
    
    def _validate_typescript_code(self, code: str) -> Dict[str, Any]:
        """Valide le code TypeScript."""
        result = {"errors": [], "warnings": [], "suggestions": []}
        
        # Detection des types any
        if re.search(r":\s*any\b", code):
            result["warnings"].append("Avoid using 'any' type")
            result["suggestions"].append("Use specific types instead of 'any'")
        
        return result
    
    # =========================================================================
    # ANALYSE DES ERREURS
    # =========================================================================
    
    def _analyze_compiler_errors(
        self,
        compiler_errors: str,
        language: Language
    ) -> Dict[str, Any]:
        """
        Analyse les erreurs de compilation.
        
        Args:
            compiler_errors: Sortie du compilateur
            language: Langage de programmation
            
        Returns:
            Dict: Analyse des erreurs
        """
        analysis = {
            "total_errors": 0,
            "error_types": {},
            "error_locations": [],
            "suggested_fixes": []
        }
        
        if not compiler_errors:
            return analysis
        
        lines = compiler_errors.split('\n')
        
        for line in lines:
            # Extraction du type d'erreur
            if "error" in line.lower():
                analysis["total_errors"] += 1
                
                # Classification
                if "syntax" in line.lower():
                    analysis["error_types"]["syntax"] = analysis["error_types"].get("syntax", 0) + 1
                elif "undeclared" in line.lower() or "not defined" in line.lower():
                    analysis["error_types"]["undeclared"] = analysis["error_types"].get("undeclared", 0) + 1
                elif "type" in line.lower():
                    analysis["error_types"]["type"] = analysis["error_types"].get("type", 0) + 1
                else:
                    analysis["error_types"]["other"] = analysis["error_types"].get("other", 0) + 1
                
                # Extraction de la localisation
                location_match = re.search(r"(\w+\.\w+):(\d+)", line)
                if location_match:
                    analysis["error_locations"].append({
                        "file": location_match.group(1),
                        "line": int(location_match.group(2))
                    })
        
        # Suggestions basees sur les types d'erreurs
        if analysis["error_types"].get("syntax", 0) > 0:
            analysis["suggested_fixes"].append("Check for missing braces, semicolons, or parentheses")
        if analysis["error_types"].get("undeclared", 0) > 0:
            analysis["suggested_fixes"].append("Check for missing imports or variable declarations")
        if analysis["error_types"].get("type", 0) > 0:
            analysis["suggested_fixes"].append("Check type compatibility and conversions")
        
        return analysis
    
    def _analyze_gas_usage(
        self,
        code: str,
        language: Language
    ) -> Dict[str, Any]:
        """
        Analyse l'utilisation du gas.
        
        Args:
            code: Code a analyser
            language: Langage de programmation
            
        Returns:
            Dict: Analyse du gas
        """
        analysis = {
            "storage_operations": 0,
            "external_calls": 0,
            "loops": 0,
            "array_operations": 0,
            "suggestions": []
        }
        
        if language != Language.SOLIDITY:
            return analysis
        
        # Detection des operations de stockage
        storage_ops = re.findall(r"\b(storage|mapping|array)\b", code)
        analysis["storage_operations"] = len(storage_ops)
        
        # Detection des appels externes
        external_calls = re.findall(r"\.(call|delegatecall|staticcall)\s*\(", code)
        analysis["external_calls"] = len(external_calls)
        
        # Detection des boucles
        loops = re.findall(r"\b(for|while)\s*\(", code)
        analysis["loops"] = len(loops)
        
        # Suggestions d'optimisation
        if analysis["storage_operations"] > 10:
            analysis["suggestions"].append("Consider reducing storage operations")
        if analysis["external_calls"] > 5:
            analysis["suggestions"].append("Consider batching external calls")
        if analysis["loops"] > 0:
            analysis["suggestions"].append("Check loop bounds and consider using unchecked blocks")
        
        return analysis
    
    # =========================================================================
    # UTILITAIRES DE PROMPT
    # =========================================================================
    
    def _build_generation_prompt(
        self,
        spec: Dict[str, Any],
        context: str,
        language: Language
    ) -> str:
        """
        Construit le prompt de generation.
        
        Args:
            spec: Specification
            context: Contexte RAG
            language: Langage de programmation
            
        Returns:
            str: Prompt complet
        """
        prompt_parts = [
            f"Generate a {language.value} smart contract based on the following specification:",
            "",
            f"Contract Name: {spec.get('name', 'Unnamed')}",
            f"Description: {spec.get('description', 'No description')}",
            f"Type: {spec.get('type', 'standard')}",
        ]
        
        if spec.get('functions'):
            prompt_parts.append("\nFunctions:")
            for func in spec.get('functions', []):
                prompt_parts.append(f"  - {func.get('name', 'unnamed')}({func.get('params', '')}) -> {func.get('returns', 'void')}")
        
        if spec.get('events'):
            prompt_parts.append("\nEvents:")
            for event in spec.get('events', []):
                prompt_parts.append(f"  - {event}")
        
        if spec.get('modifiers'):
            prompt_parts.append("\nModifiers:")
            for modifier in spec.get('modifiers', []):
                prompt_parts.append(f"  - {modifier}")
        
        if context:
            prompt_parts.append(f"\nContext from similar contracts:\n{context}")
        
        prompt_parts.extend([
            "",
            "Requirements:",
            "1. Use the latest stable version of Solidity",
            "2. Follow the ERC/EIP standards if applicable",
            "3. Include proper security measures (reentrancy guards, access control)",
            "4. Add Natspec documentation for all public functions",
            "5. Include events for important state changes",
            "6. Follow gas optimization best practices",
            "",
            "Return only the contract code, no explanations."
        ])
        
        return "\n".join(prompt_parts)
    
    def _get_system_prompt(self, language: Language) -> str:
        """
        Retourne le prompt systeme pour le LLM.
        
        Args:
            language: Langage de programmation
            
        Returns:
            str: Prompt systeme
        """
        return f"""
        You are an expert {language.value} smart contract developer.
        You write secure, optimized, and well-documented code.
        You follow best practices and industry standards.
        You never introduce vulnerabilities or anti-patterns.
        """
    
    # =========================================================================
    # EXTRACTION ET TEMPLATES
    # =========================================================================
    
    def _extract_code_from_response(self, response: str, language: Language) -> str:
        """
        Extrait le code de la reponse du LLM.
        
        Args:
            response: Reponse du LLM
            language: Langage de programmation
            
        Returns:
            str: Code extrait
        """
        # Chercher les blocs de code
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", response)
        
        if code_blocks:
            # Prendre le plus grand bloc (probablement le code)
            code = max(code_blocks, key=len)
        else:
            # Si pas de bloc, prendre toute la reponse
            code = response
        
        # Nettoyage
        code = code.strip()
        
        # Verification du langage
        if language == Language.SOLIDITY and "pragma solidity" not in code:
            # Ajout du pragma si manquant
            code = f"// SPDX-License-Identifier: MIT\npragma solidity ^0.8.24;\n\n{code}"
        
        return code
    
    def _generate_template(self, spec: Dict[str, Any], language: Language) -> str:
        """
        Genere un template de code.
        
        Args:
            spec: Specification
            language: Langage de programmation
            
        Returns:
            str: Template de code
        """
        if language == Language.SOLIDITY:
            contract_name = spec.get('name', 'TemplateContract')
            return f"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract {contract_name} {{
    // State variables
    address public owner;
    
    // Events
    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    
    // Modifiers
    modifier onlyOwner() {{
        require(msg.sender == owner, "Not owner");
        _;
    }}
    
    // Constructor
    constructor() {{
        owner = msg.sender;
    }}
    
    // Functions
    function transferOwnership(address newOwner) public onlyOwner {{
        require(newOwner != address(0), "Invalid address");
        address oldOwner = owner;
        owner = newOwner;
        emit OwnershipTransferred(oldOwner, newOwner);
    }}
}}
"""
        else:
            return f"// Template for {language.value} not available"
    
    def _generate_test_template(self, language: Language) -> str:
        """
        Genere un template de tests.
        
        Args:
            language: Langage de programmation
            
        Returns:
            str: Template de tests
        """
        if language == Language.SOLIDITY:
            return """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "forge-std/Test.sol";

contract TemplateTest is Test {
    // Test variables
    
    function setUp() public {
        // Setup code
    }
    
    function testInitialState() public {
        // Test initial state
        assertTrue(true);
    }
    
    function testFunctionality() public {
        // Test functionality
        assertTrue(true);
    }
    
    function testEdgeCases() public {
        // Test edge cases
        assertTrue(true);
    }
}
"""
        else:
            return f"// Test template for {language.value} not available"
    
    # =========================================================================
    # FIXES BASIQUES
    # =========================================================================
    
    def _apply_basic_fixes(
        self,
        code: str,
        compiler_errors: str,
        language: Language
    ) -> str:
        """
        Applique des fixes basiques.
        
        Args:
            code: Code a corriger
            compiler_errors: Erreurs de compilation
            language: Langage de programmation
            
        Returns:
            str: Code corrige
        """
        fixed_code = code
        
        if language == Language.SOLIDITY:
            # Ajout de la license si manquante
            if "SPDX-License-Identifier" not in fixed_code:
                fixed_code = "// SPDX-License-Identifier: MIT\n" + fixed_code
            
            # Ajout du pragma si manquant
            if "pragma solidity" not in fixed_code:
                fixed_code = "pragma solidity ^0.8.24;\n" + fixed_code
            
            # Correction des fonctions sans visibilite
            fixed_code = re.sub(
                r'function\s+(\w+)\s*\(([^)]*)\)\s*{',
                r'function \1(\2) public {',
                fixed_code
            )
        
        return fixed_code
    
    def _apply_basic_gas_optimizations(
        self,
        code: str,
        language: Language
    ) -> str:
        """
        Applique des optimisations de gas basiques.
        
        Args:
            code: Code a optimiser
            language: Langage de programmation
            
        Returns:
            str: Code optimise
        """
        if language != Language.SOLIDITY:
            return code
        
        optimized_code = code
        
        # Utilisation de "unchecked" pour les operations arithmetiques
        # (simplifie - dans la pratique, plus complexe)
        optimized_code = re.sub(
            r'(\w+)\s*\+\s*(\w+)',
            r'unchecked { \1 + \2 }',
            optimized_code
        )
        
        return optimized_code
    
    async def _apply_fixes_from_validation(
        self,
        code: str,
        validation: Dict[str, Any]
    ) -> Optional[str]:
        """
        Applique les corrections suggerees par la validation.
        
        Args:
            code: Code original
            validation: Resultats de validation
            
        Returns:
            Optional[str]: Code corrige ou None
        """
        if not validation.get("violations"):
            return None
        
        prompt = f"""
        Fix the following issues in the code:
        
        Issues:
        {json.dumps(validation.get("violations", []), indent=2)}
        
        Code:
        {code}
        
        Return the fixed code only.
        """
        
        try:
            if self.llm_client:
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt="You are an expert at fixing code issues.",
                    temperature=0.2
                )
                return self._extract_code_from_response(response, Language.SOLIDITY)
        except Exception as e:
            logger.warning(f"Failed to apply fixes from validation: {str(e)}")
        
        return None
    
    # =========================================================================
    # STATISTIQUES ET RAPPORTS
    # =========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.
        
        Returns:
            Dict: Statistiques detaillees
        """
        total_generations = len(self._generation_history)
        successful = sum(1 for g in self._generation_history if not g.errors)
        
        total_code_length = sum(len(g.code) for g in self._generation_history)
        
        return {
            "total_generations": total_generations,
            "successful": successful,
            "failed": total_generations - successful,
            "success_rate": successful / total_generations if total_generations > 0 else 0,
            "average_code_length": total_code_length / total_generations if total_generations > 0 else 0,
            "total_tests_generated": sum(1 for g in self._generation_history if g.tests),
            "language": self.language.value,
            "max_retries": self.max_retries,
            "optimize_gas": self.optimize_gas,
            "generate_tests": self.generate_tests,
            "generate_documentation": self.generate_documentation,
            **super().health_check()
        }
    
    def get_last_generation(self) -> Optional[GenerationResult]:
        """
        Recupere la derniere generation.
        
        Returns:
            Optional[GenerationResult]: Dernier resultat ou None
        """
        return self._generation_history[-1] if self._generation_history else None
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<DeveloperAgent(agent_id='{self.agent_id}', language='{self.language.value}', generations={len(self._generation_history)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.
        
        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "DeveloperAgent",
            "language": self.language.value,
            "generations_count": len(self._generation_history),
            "skills_count": len(self.skills),
            "max_retries": self.max_retries,
            "optimize_gas": self.optimize_gas,
            "generate_tests": self.generate_tests,
            "generate_documentation": self.generate_documentation,
            "health": self.health_check()
        }