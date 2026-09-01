# src/agents/templates/feedback_agent.py

"""
Feedback agent for the Smart Contract Dev Pipeline.
F22 – src/agents/templates/feedback_agent.py

Rôle Fonctionnel : Agent de renforcement par retroaction humaine (RLHF).
L'Agent Feedback est responsable de:
- L'analyse des retours humains (Tech Lead)
- L'interpretation des demandes de modification
- L'application des changements au code
- La validation des modifications apportees
- Le suivi de l'historique des retours
- L'amelioration continue via RLHF

Cet agent est le composant central du processus HITL (Human-In-The-Loop)
permettant l'integration des retours humains dans le pipeline.
"""
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
import logging
import json
import re
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError
from src.agents.base.best_practice import BaseBestPractice
from src.llm.llm_client import LLMClient
from src.persistence.knowledge_base import KnowledgeBase

# Configuration du logging
logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    """
    Types de retours humains.
    """
    CODE_REVIEW = "code_review"           # Revue de code
    SECURITY_CONCERN = "security_concern" # Probleme de securite
    FEATURE_REQUEST = "feature_request"   # Nouvelle fonctionnalite
    BUG_REPORT = "bug_report"             # Signalement de bug
    PERFORMANCE_ISSUE = "performance_issue" # Probleme de performance
    STYLE_ISSUE = "style_issue"           # Probleme de style
    DOCUMENTATION = "documentation"       # Amelioration documentation
    ARCHITECTURE = "architecture"         # Changement architecture
    TESTING = "testing"                   # Probleme de tests
    DEPLOYMENT = "deployment"             # Probleme de deploiement
    APPROVAL = "approval"                 # Approbation
    REJECTION = "rejection"               # Rejet
    CLARIFICATION = "clarification"       # Demande de clarification
    CUSTOM = "custom"                     # Personnalise


class FeedbackSeverity(str, Enum):
    """
    Severite des retours.
    """
    BLOCKING = "blocking"     # Bloquant - doit etre corrige avant de continuer
    CRITICAL = "critical"     # Critique - doit etre corrige
    HIGH = "high"             # Eleve - devrait etre corrige
    MEDIUM = "medium"         # Moyen - peut etre corrige
    LOW = "low"               # Faible - peut etre ignore
    SUGGESTION = "suggestion" # Suggestion - optionnel


@dataclass
class Feedback:
    """
    Represente un retour humain structure.
    
    Attributes:
        id (str): Identifiant unique du retour
        type (FeedbackType): Type de retour
        severity (FeedbackSeverity): Severite du retour
        source (str): Source du retour (ex: 'tech_lead', 'auditor')
        content (str): Contenu textuel du retour
        context (Dict): Contexte du retour (code, line numbers, etc.)
        suggested_fix (Optional[str]): Correction suggeree
        timestamp (datetime): Date du retour
        applied (bool): Le retour a-t-il ete applique ?
        applied_at (Optional[datetime]): Date d'application
        feedback_loop_count (int): Nombre d'iterations de retroaction
        metadata (Dict): Metadonnees supplementaires
    """
    id: str
    type: FeedbackType
    severity: FeedbackSeverity
    source: str
    content: str
    context: Dict[str, Any] = field(default_factory=dict)
    suggested_fix: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    applied: bool = False
    applied_at: Optional[datetime] = None
    feedback_loop_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le retour en dictionnaire."""
        return {
            "id": self.id,
            "type": self.type.value,
            "severity": self.severity.value,
            "source": self.source,
            "content": self.content,
            "context": self.context,
            "suggested_fix": self.suggested_fix,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "applied": self.applied,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "feedback_loop_count": self.feedback_loop_count,
            "metadata": self.metadata
        }


@dataclass
class FeedbackResult:
    """
    Resultat de l'application d'un retour.
    
    Attributes:
        original_code (str): Code original
        modified_code (str): Code modifie
        feedback_applied (List[str]): Retours appliques
        feedback_ignored (List[str]): Retours ignores
        changes (List[Dict]): Details des changements
        validation_passed (bool): Validation reussie ?
        validation_errors (List[str]): Erreurs de validation
        quality_score (float): Score de qualite (0-100)
        applied_at (datetime): Date d'application
    """
    original_code: str = ""
    modified_code: str = ""
    feedback_applied: List[str] = field(default_factory=list)
    feedback_ignored: List[str] = field(default_factory=list)
    changes: List[Dict[str, Any]] = field(default_factory=list)
    validation_passed: bool = True
    validation_errors: List[str] = field(default_factory=list)
    quality_score: float = 100.0
    applied_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict:
        """Convertit le resultat en dictionnaire."""
        return {
            "original_code": self.original_code,
            "modified_code": self.modified_code,
            "feedback_applied": self.feedback_applied,
            "feedback_ignored": self.feedback_ignored,
            "changes": self.changes,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "quality_score": self.quality_score,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None
        }


class FeedbackAgent(AbstractAgent):
    """
    Agent specialise dans l'incorporation des retours humains (RLHF).
    
    L'FeedbackAgent analyse les retours humains, les structure,
    et applique les modifications necessaires au code.
    
    Attributes:
        llm_client (Optional[LLMClient]): Client LLM pour l'interpretation
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG
        best_practices (List[BaseBestPractice]): Bonnes pratiques a appliquer
        max_loop_iterations (int): Nombre maximum d'iterations de retroaction
        require_validation (bool): Valider les modifications
        auto_apply_low_severity (bool): Appliquer automatiquement les retours faibles
        _feedback_history (List[Feedback]): Historique des retours
        _feedback_results (List[FeedbackResult]): Historique des resultats
    """
    
    # Patterns pour l'analyse des retours
    FEEDBACK_PATTERNS = {
        FeedbackType.CODE_REVIEW: [
            r"(?:review|check|examine|look at)\s+(?:the\s+)?code",
            r"(?:function|contract|method)\s+should",
            r"(?:suggest|recommend|propose)\s+(?:using|to use|changing)"
        ],
        FeedbackType.SECURITY_CONCERN: [
            r"(?:security|vulnerability|exploit|attack|hack)",
            r"(?:reentrancy|overflow|underflow|access control|front[- ]running)",
            r"(?:unsafe|insecure|dangerous)"
        ],
        FeedbackType.FEATURE_REQUEST: [
            r"(?:add|implement|create|include)\s+(?:a|an)?\s+(?:new\s+)?(?:feature|functionality|capability)",
            r"(?:need|want|require)\s+(?:to be able to|the ability to)"
        ],
        FeedbackType.BUG_REPORT: [
            r"(?:bug|error|issue|problem|incorrect|wrong)",
            r"(?:not working|failing|broken|malfunctioning)"
        ],
        FeedbackType.PERFORMANCE_ISSUE: [
            r"(?:gas|performance|efficiency|optimization|cost)",
            r"(?:expensive|slow|inefficient|high gas)"
        ],
        FeedbackType.STYLE_ISSUE: [
            r"(?:style|format|indentation|naming|convention)",
            r"(?:should be|could be)\s+(?:more|better)"
        ],
        FeedbackType.DOCUMENTATION: [
            r"(?:documentation|comment|natspec|explain|describe)",
            r"(?:comment|doc)\s+(?:block|string)"
        ],
        FeedbackType.ARCHITECTURE: [
            r"(?:architecture|design|pattern|structure|refactor)",
            r"(?:should|could)\s+(?:be)\s+(?:separated|extracted|refactored)"
        ],
        FeedbackType.TESTING: [
            r"(?:test|coverage|assertion|mock|fixture)",
            r"(?:test\s+should|test\s+case|test\s+scenario)"
        ],
        FeedbackType.DEPLOYMENT: [
            r"(?:deploy|deployment|network|chain|contract)",
            r"(?:constructor|init|initialize)"
        ]
    }
    
    # Mapping des severites par defaut
    DEFAULT_SEVERITY = {
        FeedbackType.BUG_REPORT: FeedbackSeverity.CRITICAL,
        FeedbackType.SECURITY_CONCERN: FeedbackSeverity.CRITICAL,
        FeedbackType.PERFORMANCE_ISSUE: FeedbackSeverity.HIGH,
        FeedbackType.ARCHITECTURE: FeedbackSeverity.HIGH,
        FeedbackType.CODE_REVIEW: FeedbackSeverity.MEDIUM,
        FeedbackType.TESTING: FeedbackSeverity.MEDIUM,
        FeedbackType.DEPLOYMENT: FeedbackSeverity.MEDIUM,
        FeedbackType.FEATURE_REQUEST: FeedbackSeverity.MEDIUM,
        FeedbackType.DOCUMENTATION: FeedbackSeverity.LOW,
        FeedbackType.STYLE_ISSUE: FeedbackSeverity.LOW,
        FeedbackType.SUGGESTION: FeedbackSeverity.LOW,
        FeedbackType.APPROVAL: FeedbackSeverity.LOW,
        FeedbackType.CLARIFICATION: FeedbackSeverity.LOW,
        FeedbackType.REJECTION: FeedbackSeverity.HIGH,
        FeedbackType.CUSTOM: FeedbackSeverity.MEDIUM
    }
    
    def __init__(
        self,
        agent_id: str,
        name: str = "FeedbackAgent",
        skills: Optional[List] = None,
        llm_client: Optional[LLMClient] = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        best_practices: Optional[List[BaseBestPractice]] = None,
        max_loop_iterations: int = 5,
        require_validation: bool = True,
        auto_apply_low_severity: bool = False
    ):
        """
        Initialise l'Agent Feedback.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (defaut: "FeedbackAgent")
            skills: Liste des competences (optionnel)
            llm_client: Client LLM pour l'interpretation
            knowledge_base: Base de connaissances RAG
            best_practices: Bonnes pratiques a appliquer
            max_loop_iterations: Nombre maximum d'iterations de retroaction
            require_validation: Valider les modifications (defaut: True)
            auto_apply_low_severity: Appliquer automatiquement les retours faibles
        """
        super().__init__(agent_id=agent_id, name=name, skills=skills, llm_client=llm_client)
        self.knowledge_base = knowledge_base
        self.best_practices = best_practices or []
        self.max_loop_iterations = max_loop_iterations
        self.require_validation = require_validation
        self.auto_apply_low_severity = auto_apply_low_severity
        self._feedback_history: List[Feedback] = []
        self._feedback_results: List[FeedbackResult] = []
        self._feedback_loop_count = 0
        
        logger.info(f"FeedbackAgent initialized: {agent_id}")
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse le retour humain et applique les modifications.
        
        Args:
            task_data: Doit contenir:
                - 'feedback': Retour humain
                - 'code': Code a modifier
                - 'source': Source du retour (optionnel)
                - 'context': Contexte du retour (optionnel)
                - 'task_id': ID de la tache (optionnel)
                
        Returns:
            Dict contenant:
            - 'status': SUCCESS ou FAILED
            - 'result': FeedbackResult en dictionnaire
            - 'code': Code modifie
            - 'feedback_applied': Retours appliques
            - 'feedback_ignored': Retours ignores
        """
        start_time = datetime.utcnow()
        
        try:
            # 1. Extraction des parametres
            feedback_content = task_data.get("feedback", "")
            code = task_data.get("code", "")
            source = task_data.get("source", "tech_lead")
            context = task_data.get("context", {})
            
            if not feedback_content:
                raise ValueError("No feedback provided")
            
            if not code:
                raise ValueError("No code provided")
            
            # 2. Analyse du retour
            feedback = await self._analyze_feedback(
                content=feedback_content,
                source=source,
                context=context
            )
            
            # 3. Sauvegarde du retour
            self._feedback_history.append(feedback)
            
            # 4. Application du retour
            result = await self._apply_feedback(
                feedback=feedback,
                code=code
            )
            
            # 5. Validation des modifications
            if self.require_validation:
                result = await self._validate_result(result)
            
            # 6. Application des bonnes pratiques
            if self.best_practices:
                result = await self._apply_best_practices(result)
            
            # 7. Persistance du resultat
            self._feedback_results.append(result)
            
            # 8. Logging de l'execution
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),
                prompt=f"Feedback from {source}: {feedback_content[:100]}...",
                response=f"Applied {len(result.feedback_applied)} changes",
                tool_output=json.dumps(result.to_dict(), indent=2)[:500]
            )
            
            logger.info(f"Feedback applied: {len(result.feedback_applied)} changes, passed={result.validation_passed}")
            
            return {
                "status": "SUCCESS",
                "result": result.to_dict(),
                "code": result.modified_code,
                "feedback_applied": result.feedback_applied,
                "feedback_ignored": result.feedback_ignored,
                "validation_passed": result.validation_passed,
                "quality_score": result.quality_score,
                "metadata": {
                    "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                    "feedback_id": feedback.id,
                    "feedback_type": feedback.type.value,
                    "feedback_severity": feedback.severity.value,
                    "loop_iteration": self._feedback_loop_count
                }
            }
            
        except Exception as e:
            logger.error(f"FeedbackAgent execution failed: {str(e)}")
            return {
                "status": "FAILED",
                "error": str(e),
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }
    
    # =========================================================================
    # ANALYSE DU RETOUR
    # =========================================================================
    
    async def _analyze_feedback(
        self,
        content: str,
        source: str,
        context: Dict[str, Any]
    ) -> Feedback:
        """
        Analyse et structure le retour humain.
        
        Args:
            content: Contenu textuel du retour
            source: Source du retour
            context: Contexte du retour
            
        Returns:
            Feedback: Retour structure
        """
        # 1. Determination du type
        feedback_type = self._detect_feedback_type(content)
        
        # 2. Determination de la severite
        severity = self._detect_feedback_severity(content, feedback_type)
        
        # 3. Extraction de la correction suggeree (si presente)
        suggested_fix = await self._extract_suggested_fix(content, context)
        
        # 4. Creation du retour
        feedback = Feedback(
            id=f"FB_{datetime.utcnow().timestamp()}_{len(self._feedback_history)}",
            type=feedback_type,
            severity=severity,
            source=source,
            content=content,
            context=context,
            suggested_fix=suggested_fix,
            feedback_loop_count=self._feedback_loop_count,
            metadata={
                "detected_by": "FeedbackAgent",
                "analysis_timestamp": datetime.utcnow().isoformat()
            }
        )
        
        logger.info(f"Feedback analyzed: type={feedback_type.value}, severity={severity.value}")
        
        return feedback
    
    def _detect_feedback_type(self, content: str) -> FeedbackType:
        """
        Detecte le type de retour.
        
        Args:
            content: Contenu textuel
            
        Returns:
            FeedbackType: Type detecte
        """
        content_lower = content.lower()
        
        # Detection par patterns
        for feedback_type, patterns in self.FEEDBACK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    return feedback_type
        
        # Detection par mots-cles
        keywords = {
            FeedbackType.SECURITY_CONCERN: ["security", "vulnerability", "exploit", "attack", "hack", "reentrancy", "overflow"],
            FeedbackType.BUG_REPORT: ["bug", "error", "issue", "problem", "incorrect", "wrong", "fail"],
            FeedbackType.PERFORMANCE_ISSUE: ["gas", "performance", "efficiency", "optimization", "cost", "expensive"],
            FeedbackType.FEATURE_REQUEST: ["add", "implement", "create", "new feature", "capability"],
            FeedbackType.APPROVAL: ["approve", "good", "fine", "okay", "accept", "valid"],
            FeedbackType.REJECTION: ["reject", "bad", "poor", "invalid", "wrong", "unacceptable"]
        }
        
        for feedback_type, words in keywords.items():
            for word in words:
                if word in content_lower:
                    return feedback_type
        
        return FeedbackType.CUSTOM
    
    def _detect_feedback_severity(
        self,
        content: str,
        feedback_type: FeedbackType
    ) -> FeedbackSeverity:
        """
        Detecte la severite du retour.
        
        Args:
            content: Contenu textuel
            feedback_type: Type de retour
            
        Returns:
            FeedbackSeverity: Severite detectee
        """
        content_lower = content.lower()
        
        # Mots-cles de severite
        if any(word in content_lower for word in ["critical", "emergency", "urgent", "blocking", "must fix", "immediately"]):
            return FeedbackSeverity.BLOCKING
        
        if any(word in content_lower for word in ["important", "necessary", "required", "should fix"]):
            return FeedbackSeverity.CRITICAL
        
        if any(word in content_lower for word in ["should", "better", "prefer", "recommend"]):
            if feedback_type in [FeedbackType.BUG_REPORT, FeedbackType.SECURITY_CONCERN]:
                return FeedbackSeverity.HIGH
            return FeedbackSeverity.MEDIUM
        
        if any(word in content_lower for word in ["could", "maybe", "option", "optional", "suggestion"]):
            return FeedbackSeverity.SUGGESTION
        
        # Severite par defaut selon le type
        return self.DEFAULT_SEVERITY.get(feedback_type, FeedbackSeverity.MEDIUM)
    
    async def _extract_suggested_fix(
        self,
        content: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extrait une correction suggeree du retour.
        
        Args:
            content: Contenu textuel
            context: Contexte
            
        Returns:
            Optional[str]: Correction suggeree ou None
        """
        # Recherche de blocs de code
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", content)
        if code_blocks:
            return code_blocks[0].strip()
        
        # Recherche de suggestions explicites
        patterns = [
            r"(?:suggest|recommend|propose)\s+(?:using|to use|changing\s+to)\s+`([^`]+)`",
            r"(?:fix|change|update)\s+to\s+`([^`]+)`",
            r"(?:should\s+be|must\s+be)\s+`([^`]+)`"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)
        
        # Si LLM disponible, tenter d'extraire une correction
        if self.llm_client:
            try:
                prompt = f"""
                Extract a specific code fix from this feedback:
                
                Feedback: {content}
                
                Return the fix as code. If no specific fix is mentioned, return 'none'.
                """
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt="You are an expert at extracting code fixes from feedback.",
                    temperature=0.2
                )
                
                if response and response.strip().lower() != 'none':
                    return response.strip()
            except Exception as e:
                logger.warning(f"Failed to extract fix via LLM: {str(e)}")
        
        return None
    
    # =========================================================================
    # APPLICATION DU RETOUR
    # =========================================================================
    
    async def _apply_feedback(
        self,
        feedback: Feedback,
        code: str
    ) -> FeedbackResult:
        """
        Applique le retour au code.
        
        Args:
            feedback: Retour a appliquer
            code: Code original
            
        Returns:
            FeedbackResult: Resultat de l'application
        """
        original_code = code
        modified_code = code
        applied = []
        ignored = []
        changes = []
        
        # Auto-application pour les retours de severite faible
        if self.auto_apply_low_severity and feedback.severity in [
            FeedbackSeverity.LOW, FeedbackSeverity.SUGGESTION
        ]:
            # Application automatique
            if feedback.suggested_fix:
                modified_code = await self._apply_fix(modified_code, feedback.suggested_fix)
                applied.append(feedback.id)
                changes.append({
                    "type": "auto_apply",
                    "feedback_id": feedback.id,
                    "change": "Applied suggested fix"
                })
        
        # Pour les retours plus severes, utilisation du LLM
        elif self.llm_client and feedback.severity in [
            FeedbackSeverity.MEDIUM, FeedbackSeverity.HIGH,
            FeedbackSeverity.CRITICAL, FeedbackSeverity.BLOCKING
        ]:
            try:
                # Generation de la nouvelle version du code
                prompt = f"""
                Apply the following feedback to the code:
                
                Feedback: {feedback.content}
                
                Code:
                {code}
                
                Requirements:
                1. Apply the feedback exactly as requested
                2. Preserve the existing functionality
                3. Maintain code quality
                4. Add comments if needed
                5. Return the complete modified code
                """
                
                if feedback.suggested_fix:
                    prompt += f"\n\nSuggested fix:\n{feedback.suggested_fix}"
                
                response = await self.llm_client.generate(
                    prompt=prompt,
                    system_prompt="You are an expert at applying feedback to code.",
                    temperature=0.3
                )
                
                # Extraction du code modifie
                modified_code = self._extract_code_from_response(response)
                
                if modified_code != code:
                    applied.append(feedback.id)
                    changes.append({
                        "type": "llm_apply",
                        "feedback_id": feedback.id,
                        "change": "Applied via LLM"
                    })
                else:
                    ignored.append(feedback.id)
                    
            except Exception as e:
                logger.error(f"LLM application failed: {str(e)}")
                ignored.append(feedback.id)
        
        else:
            # Pas de LLM disponible - application manuelle suggeree
            ignored.append(feedback.id)
            changes.append({
                "type": "manual_required",
                "feedback_id": feedback.id,
                "message": "Manual application required"
            })
        
        # Mise a jour du feedback
        feedback.applied = len(applied) > 0
        feedback.applied_at = datetime.utcnow() if feedback.applied else None
        
        return FeedbackResult(
            original_code=original_code,
            modified_code=modified_code,
            feedback_applied=applied,
            feedback_ignored=ignored,
            changes=changes
        )
    
    async def _apply_fix(self, code: str, fix: str) -> str:
        """
        Applique un correctif specifique.
        
        Args:
            code: Code original
            fix: Correctif a appliquer
            
        Returns:
            str: Code modifie
        """
        # Si le fix est un bloc de code complet
        if "contract" in fix or "function" in fix:
            # Remplacer un bloc specifique
            # Simplifie - dans la pratique, plus complexe
            return fix
        
        # Si le fix est un snippet
        # Appliquer le snippet au code
        # (implementation simplifiee)
        return code
    
    def _extract_code_from_response(self, response: str) -> str:
        """
        Extrait le code de la reponse du LLM.
        
        Args:
            response: Reponse du LLM
            
        Returns:
            str: Code extrait
        """
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", response)
        if code_blocks:
            return code_blocks[0].strip()
        return response.strip()
    
    # =========================================================================
    # VALIDATION
    # =========================================================================
    
    async def _validate_result(self, result: FeedbackResult) -> FeedbackResult:
        """
        Valide le resultat de l'application.
        
        Args:
            result: Resultat a valider
            
        Returns:
            FeedbackResult: Resultat valide
        """
        errors = []
        
        # Validation basique
        if not result.modified_code:
            errors.append("Modified code is empty")
            result.validation_passed = False
        
        if result.modified_code == result.original_code and result.feedback_applied:
            errors.append("Code unchanged despite feedback application")
            result.validation_passed = False
        
        # Validation syntaxique simplifiee
        if result.modified_code:
            if "pragma solidity" not in result.modified_code and "contract" not in result.modified_code:
                if "function" not in result.modified_code:
                    errors.append("Invalid Solidity code structure")
                    result.validation_passed = False
        
        # Validation des changements
        if result.changes:
            # Verifier que les changements sont coherents
            pass
        
        result.validation_errors = errors
        
        # Calcul du score de qualite
        result.quality_score = self._calculate_quality_score(result)
        
        return result
    
    def _calculate_quality_score(self, result: FeedbackResult) -> float:
        """
        Calcule le score de qualite.
        
        Args:
            result: Resultat de l'application
            
        Returns:
            float: Score de qualite (0-100)
        """
        score = 100.0
        
        # Deductions
        if not result.validation_passed:
            score -= 30.0
        
        if len(result.feedback_ignored) > 0:
            score -= len(result.feedback_ignored) * 5.0
        
        if result.feedback_applied and result.modified_code == result.original_code:
            score -= 20.0
        
        # Bonus
        if result.feedback_applied:
            score += 10.0
        
        return max(0.0, min(100.0, score))
    
    async def _apply_best_practices(self, result: FeedbackResult) -> FeedbackResult:
        """
        Applique les bonnes pratiques au resultat.
        
        Args:
            result: Resultat de l'application
            
        Returns:
            FeedbackResult: Resultat ameliore
        """
        for practice in self.best_practices:
            try:
                validation = await practice.validate({"code": result.modified_code})
                if not validation.get("passed", True):
                    # Application des corrections suggerees
                    for violation in validation.get("violations", []):
                        if "suggestion" in violation:
                            result.changes.append({
                                "type": "best_practice",
                                "violation": violation.get("rule_name"),
                                "suggestion": violation.get("suggestion")
                            })
                    result.quality_score = min(result.quality_score, validation.get("score", 100))
            except Exception as e:
                logger.warning(f"Best practice validation failed: {str(e)}")
        
        return result
    
    # =========================================================================
    # HISTORIQUE ET STATISTIQUES
    # =========================================================================
    
    def get_feedback_history(
        self,
        limit: Optional[int] = None,
        feedback_type: Optional[FeedbackType] = None,
        severity: Optional[FeedbackSeverity] = None
    ) -> List[Feedback]:
        """
        Recupere l'historique des retours avec filtres.
        
        Args:
            limit: Nombre maximum de retours
            feedback_type: Filtrer par type
            severity: Filtrer par severite
            
        Returns:
            List[Feedback]: Historique des retours
        """
        result = self._feedback_history
        
        if feedback_type:
            result = [f for f in result if f.type == feedback_type]
        
        if severity:
            result = [f for f in result if f.severity == severity]
        
        if limit:
            result = result[-limit:]
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.
        
        Returns:
            Dict: Statistiques detaillees
        """
        total_feedback = len(self._feedback_history)
        applied_feedback = sum(1 for f in self._feedback_history if f.applied)
        
        by_type = {}
        by_severity = {}
        
        for f in self._feedback_history:
            by_type[f.type.value] = by_type.get(f.type.value, 0) + 1
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
        
        return {
            "total_feedback": total_feedback,
            "applied_feedback": applied_feedback,
            "applied_rate": applied_feedback / total_feedback if total_feedback > 0 else 0,
            "by_type": by_type,
            "by_severity": by_severity,
            "total_results": len(self._feedback_results),
            "average_quality_score": sum(r.quality_score for r in self._feedback_results) / len(self._feedback_results) if self._feedback_results else 0,
            "feedback_loop_count": self._feedback_loop_count,
            **super().health_check()
        }
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<FeedbackAgent(agent_id='{self.agent_id}', feedback={len(self._feedback_history)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.
        
        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "FeedbackAgent",
            "feedback_count": len(self._feedback_history),
            "results_count": len(self._feedback_results),
            "skills_count": len(self.skills),
            "max_loop_iterations": self.max_loop_iterations,
            "require_validation": self.require_validation,
            "auto_apply_low_severity": self.auto_apply_low_severity,
            "health": self.health_check()
        }
    
    # =========================================================================
    # INTERACTION AVEC L'HUMAIN (HITL)
    # =========================================================================
    
    async def request_clarification(
        self,
        feedback: Feedback,
        questions: List[str]
    ) -> Dict[str, Any]:
        """
        Demande une clarification a l'humain.
        
        Args:
            feedback: Retour necessitant clarification
            questions: Questions a poser
            
        Returns:
            Dict: Demande de clarification
        """
        return {
            "feedback_id": feedback.id,
            "type": "clarification_request",
            "questions": questions,
            "context": feedback.context,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def generate_feedback_summary(self) -> str:
        """
        Genere un resume des retours.
        
        Returns:
            str: Resume des retours
        """
        if not self._feedback_history:
            return "No feedback received."
        
        lines = [
            "📊 Feedback Summary",
            "=" * 40,
            f"Total feedback: {len(self._feedback_history)}",
            f"Applied: {sum(1 for f in self._feedback_history if f.applied)}",
            f"Pending: {sum(1 for f in self._feedback_history if not f.applied)}",
            "",
            "📌 By Type:"
        ]
        
        by_type = {}
        for f in self._feedback_history:
            by_type[f.type.value] = by_type.get(f.type.value, 0) + 1
        
        for type_name, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - {type_name}: {count}")
        
        lines.append("")
        lines.append("📌 By Severity:")
        
        by_severity = {}
        for f in self._feedback_history:
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1
        
        for sev, count in sorted(by_severity.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - {sev}: {count}")
        
        # Derniers retours
        if self._feedback_history:
            lines.append("")
            lines.append("📌 Recent Feedback:")
            for f in self._feedback_history[-3:]:
                lines.append(f"  - [{f.type.value}] {f.content[:100]}...")
        
        return "\n".join(lines)