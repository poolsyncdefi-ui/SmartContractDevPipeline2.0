# src/agents/base/best_practice.py

"""
Base best practice validation module for the Smart Contract Dev Pipeline.
F16 – src/agents/base/best_practice.py

Rôle Fonctionnel : Fournit les directives de bonnes pratiques et validation.
Ce module definit la classe de base pour la validation des bonnes pratiques
dans le pipeline. Il permet de verifier que le code genere respecte les
standards de qualite, de securite et de maintenabilite.

Les validations couvrent:
- Standards de codage Solidity (style, nommage)
- Patrons de conception (Design Patterns)
- Securite (OWASP, Smart Contract Security)
- Performances (gas optimization)
- Documentation et commentaires
- Tests et couverture

Les pratiques peuvent etre appliquees a differents niveaux:
- Niveau 1: Syntaxe et style de base
- Niveau 2: Patterns et architecture
- Niveau 3: Securite avancee
- Niveau 4: Performance et optimisation
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from datetime import datetime
import json
import logging
import re
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.models import BestPractice as BestPracticeConfig
from src.core.exceptions import PipelineError

# Configuration du logging
logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """
    Niveaux de severite pour les validations.
    """
    CRITICAL = "critical"      # Bloquant - doit etre corrige
    HIGH = "high"              # Urgent - doit etre corrige rapidement
    MEDIUM = "medium"          # Important - devrait etre corrige
    LOW = "low"                # Mineur - peut etre ignore temporairement
    INFO = "info"              # Information - recommandation


class ValidationCategory(str, Enum):
    """
    Categories de validation.
    """
    SECURITY = "security"           # Securite
    STYLE = "style"                 # Style de code
    PERFORMANCE = "performance"     # Performance
    ARCHITECTURE = "architecture"   # Architecture
    DOCUMENTATION = "documentation" # Documentation
    TESTING = "testing"             # Tests
    MAINTAINABILITY = "maintainability" # Maintenabilite
    COMPLIANCE = "compliance"       # Conformite


class BestPracticeLevel(str, Enum):
    """
    Niveaux d'application des bonnes pratiques.
    """
    BASIC = "basic"         # Pratiques de base
    STANDARD = "standard"   # Pratiques standard
    ADVANCED = "advanced"   # Pratiques avancees
    EXPERT = "expert"       # Pratiques expertes


@dataclass
class ValidationRule:
    """
    Regle de validation individuelle.
    
    Attributes:
        rule_id (str): Identifiant unique de la regle
        name (str): Nom descriptif de la regle
        description (str): Description detaillee
        category (ValidationCategory): Categorie de la regle
        severity (ValidationSeverity): Severite de la regle
        pattern (Optional[str]): Pattern regex pour la detection
        message (str): Message a afficher en cas de violation
        fix_suggestion (Optional[str]): Suggestion de correction
    """
    rule_id: str
    name: str
    description: str
    category: ValidationCategory
    severity: ValidationSeverity
    pattern: Optional[str] = None
    message: str = ""
    fix_suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """
    Resultat d'une validation.
    
    Attributes:
        passed (bool): Indique si la validation est reussie
        severity (ValidationSeverity): Severite maximale des violations
        violations (List[Dict]): Liste des violations trouvees
        warnings (List[Dict]): Liste des avertissements
        suggestions (List[Dict]): Liste des suggestions
        score (float): Score de qualite (0-100)
        details (Dict): Details supplementaires
    """
    passed: bool = True
    severity: ValidationSeverity = ValidationSeverity.INFO
    violations: List[Dict] = field(default_factory=list)
    warnings: List[Dict] = field(default_factory=list)
    suggestions: List[Dict] = field(default_factory=list)
    score: float = 100.0
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le resultat en dictionnaire."""
        return {
            "passed": self.passed,
            "severity": self.severity.value,
            "violations": self.violations,
            "warnings": self.warnings,
            "suggestions": self.suggestions,
            "score": self.score,
            "details": self.details
        }
    
    def add_violation(self, rule: ValidationRule, context: Dict) -> None:
        """Ajoute une violation."""
        self.violations.append({
            "rule_id": rule.rule_id,
            "rule_name": rule.name,
            "severity": rule.severity.value,
            "message": rule.message,
            "context": context,
            "suggestion": rule.fix_suggestion
        })
        self.passed = False
        if self._get_severity_order(rule.severity) < self._get_severity_order(self.severity):
            self.severity = rule.severity
        self.score = max(0, self.score - 10)
    
    def add_warning(self, rule: ValidationRule, context: Dict) -> None:
        """Ajoute un avertissement."""
        self.warnings.append({
            "rule_id": rule.rule_id,
            "rule_name": rule.name,
            "severity": rule.severity.value,
            "message": rule.message,
            "context": context,
            "suggestion": rule.fix_suggestion
        })
        self.score = max(0, self.score - 5)
    
    def add_suggestion(self, suggestion: str, context: Dict) -> None:
        """Ajoute une suggestion."""
        self.suggestions.append({
            "suggestion": suggestion,
            "context": context
        })
        self.score = min(100, self.score + 2)
    
    @staticmethod
    def _get_severity_order(severity: ValidationSeverity) -> int:
        """Retourne l'ordre de severite."""
        order = {
            ValidationSeverity.CRITICAL: 0,
            ValidationSeverity.HIGH: 1,
            ValidationSeverity.MEDIUM: 2,
            ValidationSeverity.LOW: 3,
            ValidationSeverity.INFO: 4
        }
        return order.get(severity, 4)


class BaseBestPractice(ABC):
    """
    Classe de base pour les bonnes pratiques.
    
    Cette classe fournit l'infrastructure pour valider le code genere
    contre un ensemble de bonnes pratiques. Elle peut etre etendue
    pour des validations specifiques a un langage ou a un domaine.
    
    Attributes:
        config (BestPracticeConfig): Configuration des bonnes pratiques
        rules (List[ValidationRule]): Liste des regles de validation
        level (BestPracticeLevel): Niveau d'application
        enabled_categories (Set[ValidationCategory]): Categories activees
        strict_mode (bool): Mode strict (toutes les violations bloquent)
        auto_fix (bool): Tentative de correction automatique
    """
    
    def __init__(
        self, 
        config: BestPracticeConfig,
        level: BestPracticeLevel = BestPracticeLevel.STANDARD,
        strict_mode: bool = False,
        auto_fix: bool = False,
        enabled_categories: Optional[Set[ValidationCategory]] = None
    ):
        """
        Initialise le validateur de bonnes pratiques.
        
        Args:
            config: Configuration des bonnes pratiques
            level: Niveau d'application (defaut: STANDARD)
            strict_mode: Mode strict (defaut: False)
            auto_fix: Tentative de correction automatique (defaut: False)
            enabled_categories: Categories activees (defaut: toutes)
        """
        self.config = config
        self.level = level
        self.strict_mode = strict_mode
        self.auto_fix = auto_fix
        self.enabled_categories = enabled_categories or set(ValidationCategory)
        self.rules: List[ValidationRule] = []
        self._rule_registry: Dict[str, ValidationRule] = {}
        
        # Chargement des regles par defaut
        self._load_default_rules()
        
        logger.info(f"BestPractice initialized: {config.practice_id} (level={level.value})")
    
    @abstractmethod
    async def validate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valide la sortie d'une competence.
        
        Cette methode doit etre implementee par chaque validateur specifique.
        Elle analyse le contenu et retourne un rapport de validation detaille.
        
        Args:
            output: Sortie de la competence a valider
            
        Returns:
            Dict contenant les resultats de validation:
            - passed: bool
            - severity: str
            - violations: List[Dict]
            - warnings: List[Dict]
            - suggestions: List[Dict]
            - score: float
            - details: Dict
            
        Raises:
            PipelineError: Si la validation echoue de maniere critique
        """
        pass
    
    async def validate_with_context(
        self, 
        output: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> ValidationResult:
        """
        Valide avec contexte supplementaire.
        
        Args:
            output: Sortie a valider
            context: Contexte additionnel pour la validation
            
        Returns:
            ValidationResult: Resultat detaille de la validation
        """
        result = ValidationResult()
        
        try:
            # Execution de la validation principale
            validation_result = await self.validate(output)
            
            # Construction du resultat structure
            result.passed = validation_result.get("passed", True)
            result.severity = ValidationSeverity(
                validation_result.get("severity", "info")
            )
            result.violations = validation_result.get("violations", [])
            result.warnings = validation_result.get("warnings", [])
            result.suggestions = validation_result.get("suggestions", [])
            result.score = validation_result.get("score", 100.0)
            result.details = validation_result.get("details", {})
            
            # Ajout du contexte si fourni
            if context:
                result.details["context"] = context
            
            # Verification supplementaire en mode strict
            if self.strict_mode and not result.passed:
                logger.warning("Strict mode: validation failed")
                result.details["strict_mode"] = True
            
        except Exception as e:
            logger.error(f"Validation failed with error: {str(e)}")
            result.passed = False
            result.severity = ValidationSeverity.CRITICAL
            result.details["error"] = str(e)
        
        return result
    
    def get_rules(self, category: Optional[ValidationCategory] = None) -> List[ValidationRule]:
        """
        Retourne les regles de validation.
        
        Args:
            category: Filtrer par categorie (optionnel)
            
        Returns:
            List[ValidationRule]: Liste des regles
        """
        if category:
            return [r for r in self.rules if r.category == category]
        return self.rules.copy()
    
    def add_rule(self, rule: ValidationRule) -> None:
        """
        Ajoute une regle de validation.
        
        Args:
            rule: Regle a ajouter
            
        Raises:
            ValueError: Si la regle est invalide
        """
        if not rule.rule_id:
            raise ValueError("Rule must have an ID")
        
        if rule.rule_id in self._rule_registry:
            logger.warning(f"Rule {rule.rule_id} already exists, overwriting")
        
        self.rules.append(rule)
        self._rule_registry[rule.rule_id] = rule
        logger.debug(f"Rule added: {rule.rule_id}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """
        Supprime une regle de validation.
        
        Args:
            rule_id: Identifiant de la regle
            
        Returns:
            bool: True si supprime, False sinon
        """
        if rule_id in self._rule_registry:
            self.rules = [r for r in self.rules if r.rule_id != rule_id]
            del self._rule_registry[rule_id]
            logger.debug(f"Rule removed: {rule_id}")
            return True
        return False
    
    def enable_category(self, category: ValidationCategory) -> None:
        """Active une categorie de validation."""
        self.enabled_categories.add(category)
        logger.info(f"Category enabled: {category.value}")
    
    def disable_category(self, category: ValidationCategory) -> None:
        """Desactive une categorie de validation."""
        self.enabled_categories.discard(category)
        logger.info(f"Category disabled: {category.value}")
    
    def is_category_enabled(self, category: ValidationCategory) -> bool:
        """
        Verifie si une categorie est activee.
        
        Args:
            category: Categorie a verifier
            
        Returns:
            bool: True si activee
        """
        return category in self.enabled_categories
    
    def get_report(self, result: ValidationResult) -> Dict[str, Any]:
        """
        Genere un rapport detaille de validation.
        
        Args:
            result: Resultat de validation
            
        Returns:
            Dict: Rapport detaille
        """
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "practice_id": self.config.practice_id,
            "practice_name": self.config.title,
            "level": self.level.value,
            "strict_mode": self.strict_mode,
            "auto_fix": self.auto_fix,
            "summary": {
                "passed": result.passed,
                "severity": result.severity.value,
                "violations_count": len(result.violations),
                "warnings_count": len(result.warnings),
                "suggestions_count": len(result.suggestions),
                "score": result.score
            },
            "violations": result.violations,
            "warnings": result.warnings,
            "suggestions": result.suggestions,
            "details": result.details
        }
    
    def _load_default_rules(self) -> None:
        """
        Charge les regles par defaut.
        
        Cette methode peut etre surchargee par les classes filles
        pour fournir des regles specifiques.
        """
        # Regles de base communes a tous les validations
        default_rules = [
            ValidationRule(
                rule_id="BP001",
                name="No trailing whitespace",
                description="Trailing whitespace should be removed",
                category=ValidationCategory.STYLE,
                severity=ValidationSeverity.LOW,
                pattern=r"\s+$",
                message="Trailing whitespace detected",
                fix_suggestion="Remove trailing whitespace"
            ),
            ValidationRule(
                rule_id="BP002",
                name="Explicit function visibility",
                description="All functions should have explicit visibility",
                category=ValidationCategory.STYLE,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"function\s+\w+\s*\(",
                message="Function missing explicit visibility",
                fix_suggestion="Add 'public', 'internal', or 'private' visibility"
            ),
            ValidationRule(
                rule_id="BP003",
                name="No hardcoded credentials",
                description="Credentials should not be hardcoded",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.CRITICAL,
                pattern=r"(?:password|secret|key|token)\s*=\s*[\"\'][^\"\']+[\"\']",
                message="Hardcoded credential detected",
                fix_suggestion="Use environment variables or secrets manager"
            ),
            ValidationRule(
                rule_id="BP004",
                name="Function documentation",
                description="Public functions should be documented",
                category=ValidationCategory.DOCUMENTATION,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"function\s+\w+\s*\([^)]*\)\s+(?:public|external)\s*{",
                message="Public function missing documentation",
                fix_suggestion="Add natspec documentation"
            ),
            ValidationRule(
                rule_id="BP005",
                name="Modifier usage",
                description="Use modifiers for access control",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.HIGH,
                pattern=r"function\s+\w+\s*\([^)]*\)\s+public\s+{",
                message="Function may need access control modifier",
                fix_suggestion="Add 'onlyOwner' or custom modifier"
            )
        ]
        
        for rule in default_rules:
            if self.is_category_enabled(rule.category):
                self.add_rule(rule)
    
    def _check_pattern(self, content: str, pattern: str) -> List[Tuple[int, str]]:
        """
        Verifie un pattern dans le contenu.
        
        Args:
            content: Contenu a verifier
            pattern: Pattern regex a chercher
            
        Returns:
            List[Tuple[int, str]]: Liste des (position, match)
        """
        matches = []
        for match in re.finditer(pattern, content, re.MULTILINE):
            line_number = content[:match.start()].count('\n') + 1
            matches.append((line_number, match.group()))
        return matches
    
    def _apply_auto_fix(self, content: str, violations: List[Dict]) -> str:
        """
        Applique des corrections automatiques.
        
        Args:
            content: Contenu original
            violations: Liste des violations
            
        Returns:
            str: Contenu corrige
        """
        if not self.auto_fix or not violations:
            return content
        
        fixed_content = content
        
        # Application des corrections
        for violation in violations:
            rule_id = violation.get("rule_id")
            rule = self._rule_registry.get(rule_id)
            
            if rule and rule.fix_suggestion:
                # Application de la correction specifique
                if rule_id == "BP001":  # Trailing whitespace
                    fixed_content = re.sub(r"\s+$", "", fixed_content, flags=re.MULTILINE)
                elif rule_id == "BP003":  # Hardcoded credentials
                    # Marquer comme a remplacer (plus complexe)
                    pass
        
        return fixed_content
    
    def __repr__(self) -> str:
        return f"<BaseBestPractice(practice_id='{self.config.practice_id}', level='{self.level.value}')>"
    
    def to_dict(self) -> Dict:
        """
        Convertit le validateur en dictionnaire.
        
        Returns:
            Dict: Representation dictionnaire
        """
        return {
            "practice_id": self.config.practice_id,
            "title": self.config.title,
            "level": self.level.value,
            "strict_mode": self.strict_mode,
            "auto_fix": self.auto_fix,
            "enabled_categories": [c.value for c in self.enabled_categories],
            "rules_count": len(self.rules)
        }


# =============================================================================
# CLASSES DE BASE SPECIFIQUES PAR DOMAINE
# =============================================================================

class SolidityBestPractice(BaseBestPractice):
    """
    Bonnes pratiques specifiques au developpement Solidity.
    """
    
    def __init__(self, config: BestPracticeConfig, **kwargs):
        super().__init__(config, **kwargs)
        self._load_solidity_rules()
    
    async def validate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valide le code Solidity.
        
        Args:
            output: Doit contenir 'code' ou 'contract' comme cle
            
        Returns:
            Dict: Resultat de validation
        """
        result = ValidationResult()
        
        # Extraction du code a valider
        code = output.get("code") or output.get("contract") or output.get("content")
        if not code:
            result.passed = False
            result.details["error"] = "No code found in output"
            return result.to_dict()
        
        # Validation des regles
        for rule in self.rules:
            if not self.is_category_enabled(rule.category):
                continue
            
            if rule.pattern:
                matches = self._check_pattern(code, rule.pattern)
                if matches:
                    for line, match in matches:
                        context = {"line": line, "match": match}
                        if rule.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.HIGH]:
                            result.add_violation(rule, context)
                        else:
                            result.add_warning(rule, context)
        
        # Application des corrections si active
        if self.auto_fix and result.violations:
            code_fixed = self._apply_auto_fix(code, result.violations)
            result.details["fixed_code"] = code_fixed
            result.details["fix_applied"] = True
        
        return result.to_dict()
    
    def _load_solidity_rules(self) -> None:
        """
        Charge les regles specifiques Solidity.
        """
        solidity_rules = [
            ValidationRule(
                rule_id="SOL001",
                name="SPDX License Identifier",
                description="Contract must have SPDX license identifier",
                category=ValidationCategory.COMPLIANCE,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"\/\/ SPDX-License-Identifier:",
                message="Missing SPDX license identifier",
                fix_suggestion="Add '// SPDX-License-Identifier: MIT'"
            ),
            ValidationRule(
                rule_id="SOL002",
                name="Pragma Version",
                description="Pragma version should be specified",
                category=ValidationCategory.COMPLIANCE,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"pragma solidity",
                message="Missing pragma solidity statement",
                fix_suggestion="Add 'pragma solidity ^0.8.0;'"
            ),
            ValidationRule(
                rule_id="SOL003",
                name="Reentrancy Guard",
                description="Consider using reentrancy guard",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.HIGH,
                pattern=r"function\s+\w+\s*\([^)]*\)\s+(?:public|external)\s+[^{]*{",
                message="Function may be vulnerable to reentrancy",
                fix_suggestion="Add 'nonReentrant' modifier or use Checks-Effects-Interactions"
            ),
            ValidationRule(
                rule_id="SOL004",
                name="Event Naming",
                description="Events should be in past tense",
                category=ValidationCategory.STYLE,
                severity=ValidationSeverity.LOW,
                pattern=r"event\s+\w+[^d]$",
                message="Event name should be in past tense",
                fix_suggestion="Use past tense (e.g., 'Transfer', 'Approval')"
            ),
            ValidationRule(
                rule_id="SOL005",
                name="Constructor Name",
                description="Constructor should use 'constructor' keyword",
                category=ValidationCategory.STYLE,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"function\s+\w+\s*\([^)]*\)\s+(?:public|internal|external)\s+{",
                message="Using function as constructor (pre-0.4.22 style)",
                fix_suggestion="Use 'constructor()' instead"
            )
        ]
        
        for rule in solidity_rules:
            if self.is_category_enabled(rule.category):
                self.add_rule(rule)
    
    def __repr__(self) -> str:
        return f"<SolidityBestPractice(practice_id='{self.config.practice_id}')>"


class JavaScriptBestPractice(BaseBestPractice):
    """
    Bonnes pratiques specifiques au developpement JavaScript/TypeScript.
    """
    
    async def validate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Valide le code JavaScript/TypeScript.
        
        Args:
            output: Doit contenir 'code' comme cle
            
        Returns:
            Dict: Resultat de validation
        """
        result = ValidationResult()
        
        code = output.get("code") or output.get("content")
        if not code:
            result.passed = False
            result.details["error"] = "No code found in output"
            return result.to_dict()
        
        # Validation des regles
        for rule in self.rules:
            if not self.is_category_enabled(rule.category):
                continue
            
            if rule.pattern:
                matches = self._check_pattern(code, rule.pattern)
                if matches:
                    for line, match in matches:
                        context = {"line": line, "match": match}
                        if rule.severity in [ValidationSeverity.CRITICAL, ValidationSeverity.HIGH]:
                            result.add_violation(rule, context)
                        else:
                            result.add_warning(rule, context)
        
        return result.to_dict()
    
    def _load_default_rules(self) -> None:
        """Charge les regles par defaut pour JavaScript."""
        super()._load_default_rules()
        
        js_rules = [
            ValidationRule(
                rule_id="JS001",
                name="Use 'const' and 'let'",
                description="Avoid using 'var'",
                category=ValidationCategory.STYLE,
                severity=ValidationSeverity.LOW,
                pattern=r"\bvar\s+",
                message="'var' used instead of 'const' or 'let'",
                fix_suggestion="Replace with 'const' or 'let'"
            ),
            ValidationRule(
                rule_id="JS002",
                name="Async/Await usage",
                description="Prefer async/await over callbacks",
                category=ValidationCategory.PERFORMANCE,
                severity=ValidationSeverity.MEDIUM,
                pattern=r"\.then\s*\(",
                message="Use async/await instead of .then() chains",
                fix_suggestion="Refactor to use async/await"
            ),
            ValidationRule(
                rule_id="JS003",
                name="Error handling",
                description="Always handle errors in async functions",
                category=ValidationCategory.SECURITY,
                severity=ValidationSeverity.HIGH,
                pattern=r"async\s+function\s+\w+\s*\([^)]*\)\s*{",
                message="Async function missing try/catch",
                fix_suggestion="Add try/catch for error handling"
            )
        ]
        
        for rule in js_rules:
            if self.is_category_enabled(rule.category):
                self.add_rule(rule)


# =============================================================================
# VALIDATEUR COMPOSITE
# =============================================================================

class CompositeBestPractice(BaseBestPractice):
    """
    Validateur composite qui combine plusieurs validateurs.
    """
    
    def __init__(self, config: BestPracticeConfig, validators: List[BaseBestPractice] = None):
        super().__init__(config)
        self.validators = validators or []
    
    async def validate(self, output: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute tous les validateurs et combine les resultats.
        
        Args:
            output: Sortie a valider
            
        Returns:
            Dict: Resultat combine des validations
        """
        combined_result = ValidationResult()
        
        for validator in self.validators:
            try:
                result_dict = await validator.validate(output)
                
                # Aggregation des resultats
                combined_result.violations.extend(result_dict.get("violations", []))
                combined_result.warnings.extend(result_dict.get("warnings", []))
                combined_result.suggestions.extend(result_dict.get("suggestions", []))
                
                if not result_dict.get("passed", True):
                    combined_result.passed = False
                
                severity_str = result_dict.get("severity", "info")
                severity = ValidationSeverity(severity_str)
                if ValidationResult._get_severity_order(severity) < ValidationResult._get_severity_order(combined_result.severity):
                    combined_result.severity = severity
                
                combined_result.score = min(
                    combined_result.score,
                    result_dict.get("score", 100.0)
                )
                
                # Details
                details = result_dict.get("details", {})
                combined_result.details[f"validator_{validator.config.practice_id}"] = details
                
            except Exception as e:
                logger.error(f"Validator {validator.config.practice_id} failed: {str(e)}")
                combined_result.details[f"error_{validator.config.practice_id}"] = str(e)
        
        return combined_result.to_dict()
    
    def add_validator(self, validator: BaseBestPractice) -> None:
        """Ajoute un validateur au composite."""
        self.validators.append(validator)
        logger.info(f"Validator added: {validator.config.practice_id}")
    
    def remove_validator(self, practice_id: str) -> bool:
        """Supprime un validateur du composite."""
        initial_count = len(self.validators)
        self.validators = [v for v in self.validators if v.config.practice_id != practice_id]
        return len(self.validators) < initial_count