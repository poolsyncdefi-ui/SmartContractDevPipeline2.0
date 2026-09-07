# src/agents/templates/feedback_agent.py[cite: 17]

"""
Feedback agent for the Smart Contract Dev Pipeline[cite: 17].
F22 – src/agents/templates/feedback_agent.py[cite: 17]

Role Fonctionnel : Agent de renforcement par retroaction humaine (RLHF).[cite: 17]
L'Agent Feedback est responsable de:[cite: 17]
- L'analyse des retours humains (Tech Lead)[cite: 17]
- L'interpretation des demandes de modification[cite: 17]
- L'application des changements au code[cite: 17]
- La validation des modifications apportees[cite: 17]
- Le suivi de l'historique des retours[cite: 17]
- L'amelioration continue via RLHF[cite: 17]

Cet agent est le composant central du processus HITL (Human-In-The-Loop)[cite: 17]
permettant l'integration des retours humains dans le pipeline.[cite: 17]
"""
from src.agents.base.abstract_agent import AbstractAgent[cite: 17]
from typing import Dict, Any, List, Optional, Set, Tuple[cite: 17]
from datetime import datetime[cite: 17]
import logging[cite: 17]
import json[cite: 17]
import re[cite: 17]
from enum import Enum[cite: 17]
from dataclasses import dataclass, field[cite: 17]

# Import des modules du pipeline[cite: 17]
from src.core.exceptions import PipelineError, LLMError[cite: 17]
from src.agents.base.best_practice import BaseBestPractice[cite: 17]
from src.llm.llm_client import LLMClient[cite: 17]
from src.persistence.knowledge_base import KnowledgeBase[cite: 17]

# Configuration du logging[cite: 17]
logger = logging.getLogger(__name__)[cite: 17]


class FeedbackType(str, Enum):[cite: 17]
    """
    Types de retours humains.[cite: 17]
    """
    CODE_REVIEW = "code_review"           # Revue de code[cite: 17]
    SECURITY_CONCERN = "security_concern" # Probleme de securite[cite: 17]
    FEATURE_REQUEST = "feature_request"   # Nouvelle fonctionnalite[cite: 17]
    BUG_REPORT = "bug_report"             # Signalement de bug[cite: 17]
    PERFORMANCE_ISSUE = "performance_issue" # Probleme de performance[cite: 17]
    STYLE_ISSUE = "style_issue"           # Probleme de style[cite: 17]
    DOCUMENTATION = "documentation"       # Amelioration documentation[cite: 17]
    ARCHITECTURE = "architecture"         # Changement architecture[cite: 17]
    TESTING = "testing"                   # Probleme de tests[cite: 17]
    DEPLOYMENT = "deployment"             # Probleme de deploiement[cite: 17]
    APPROVAL = "approval"                 # Approbation[cite: 17]
    REJECTION = "rejection"               # Rejet[cite: 17]
    CLARIFICATION = "clarification"       # Demande de clarification[cite: 17]
    CUSTOM = "custom"                     # Personnalise[cite: 17]


class FeedbackSeverity(str, Enum):[cite: 17]
    """
    Severite des retours.[cite: 17]
    """
    BLOCKING = "blocking"     # Bloquant - doit etre corrige avant de continuer[cite: 17]
    CRITICAL = "critical"     # Critique - doit etre corrige[cite: 17]
    HIGH = "high"             # Eleve - devrait etre corrige[cite: 17]
    MEDIUM = "medium"         # Moyen - peut etre corrige[cite: 17]
    LOW = "low"               # Faible - peut etre ignore[cite: 17]
    SUGGESTION = "suggestion" # Suggestion - optionnel[cite: 17]


@dataclass
class Feedback:[cite: 17]
    """
    Represente un retour humain structure.[cite: 17]

    Attributes:[cite: 17]
        id (str): Identifiant unique du retour[cite: 17]
        type (FeedbackType): Type de retour[cite: 17]
        severity (FeedbackSeverity): Severite du retour[cite: 17]
        source (str): Source du retour (ex: 'tech_lead', 'auditor')[cite: 17]
        content (str): Contenu textuel du retour[cite: 17]
        context (Dict): Contexte du retour (code, line numbers, etc.)[cite: 17]
        suggested_fix (Optional[str]): Correction suggeree[cite: 17]
        timestamp (datetime): Date du retour[cite: 17]
        applied (bool): Le retour a-t-il ete applique ?[cite: 17]
        applied_at (Optional[datetime]): Date d'application[cite: 17]
        feedback_loop_count (int): Nombre d'iterations de retroaction[cite: 17]
        metadata (Dict): Metadonnees supplementaires[cite: 17]
    """
    id: str[cite: 17]
    type: FeedbackType[cite: 17]
    severity: FeedbackSeverity[cite: 17]
    source: str[cite: 17]
    content: str[cite: 17]
    context: Dict[str, Any] = field(default_factory=dict)[cite: 17]
    suggested_fix: Optional[str] = None[cite: 17]
    timestamp: datetime = field(default_factory=datetime.utcnow)[cite: 17]
    applied: bool = False[cite: 17]
    applied_at: Optional[datetime] = None[cite: 17]
    feedback_loop_count: int = 0[cite: 17]
    metadata: Dict[str, Any] = field(default_factory=dict)[cite: 17]

    def to_dict(self) -> Dict:[cite: 17]
        """Convertit le retour en dictionnaire."""[cite: 17]
        return {[cite: 17]
            "id": self.id,[cite: 17]
            "type": self.type.value,[cite: 17]
            "severity": self.severity.value,[cite: 17]
            "source": self.source,[cite: 17]
            "content": self.content,[cite: 17]
            "context": self.context,[cite: 17]
            "suggested_fix": self.suggested_fix,[cite: 17]
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,[cite: 17]
            "applied": self.applied,[cite: 17]
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,[cite: 17]
            "feedback_loop_count": self.feedback_loop_count,[cite: 17]
            "metadata": self.metadata[cite: 17]
        }


@dataclass
class FeedbackResult:[cite: 17]
    """
    Resultat de l'application d'un retour.[cite: 17]

    Attributes:[cite: 17]
        original_code (str): Code original[cite: 17]
        modified_code (str): Code modifie[cite: 17]
        feedback_applied (List[str]): Retours appliques[cite: 17]
        feedback_ignored (List[str]): Retours ignores[cite: 17]
        changes (List[Dict]): Details des changements[cite: 17]
        validation_passed (bool): Validation reussie ?[cite: 17]
        validation_errors (List[str]): Erreurs de validation[cite: 17]
        quality_score (float): Score de qualite (0-100)[cite: 17]
        applied_at (datetime): Date d'application[cite: 17]
    """
    original_code: str = ""[cite: 17]
    modified_code: str = ""[cite: 17]
    feedback_applied: List[str] = field(default_factory=list)[cite: 17]
    feedback_ignored: List[str] = field(default_factory=list)[cite: 17]
    changes: List[Dict[str, Any]] = field(default_factory=list)[cite: 17]
    validation_passed: bool = True[cite: 17]
    validation_errors: List[str] = field(default_factory=list)[cite: 17]
    quality_score: float = 100.0[cite: 17]
    applied_at: datetime = field(default_factory=datetime.utcnow)[cite: 17]

    def to_dict(self) -> Dict:[cite: 17]
        """Convertit le resultat en dictionnaire."""[cite: 17]
        return {[cite: 17]
            "original_code": self.original_code,[cite: 17]
            "modified_code": self.modified_code,[cite: 17]
            "feedback_applied": self.feedback_applied,[cite: 17]
            "feedback_ignored": self.feedback_ignored,[cite: 17]
            "changes": self.changes,[cite: 17]
            "validation_passed": self.validation_passed,[cite: 17]
            "validation_errors": self.validation_errors,[cite: 17]
            "quality_score": self.quality_score,[cite: 17]
            "applied_at": self.applied_at.isoformat() if self.applied_at else None[cite: 17]
        }


class FeedbackAgent(AbstractAgent):[cite: 17]
    """
    Agent specialise dans l'incorporation des retours humains (RLHF).[cite: 17]

    L'FeedbackAgent analyse les retours humains, les structure,[cite: 17]
    et applique les modifications necessaires au code.[cite: 17]

    Attributes:[cite: 17]
        llm_client (Optional[LLMClient]): Client LLM pour l'interpretation[cite: 17]
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances RAG[cite: 17]
        best_practices (List[BaseBestPractice]): Bonnes pratiques a appliquer[cite: 17]
        max_loop_iterations (int): Nombre maximum d'iterations de retroaction[cite: 17]
        require_validation (bool): Valider les modifications[cite: 17]
        auto_apply_low_severity (bool): Appliquer automatiquement les retours faibles[cite: 17]
        _feedback_history (List[Feedback]): Historique des retours[cite: 17]
        _feedback_results (List[FeedbackResult]): Historique des resultats[cite: 17]
    """

    # Patterns pour l'analyse des retours[cite: 17]
    FEEDBACK_PATTERNS = {[cite: 17]
        FeedbackType.CODE_REVIEW: [[cite: 17]
            r"(?:review|check|examine|look at)\s+(?:the\s+)?code",[cite: 17]
            r"(?:function|contract|method)\s+should",[cite: 17]
            r"(?:suggest|recommend|propose)\s+(?:using|to use|changing)"[cite: 17]
        ],[cite: 17]
        FeedbackType.SECURITY_CONCERN: [[cite: 17]
            r"(?:security|vulnerability|exploit|attack|hack)",[cite: 17]
            r"(?:reentrancy|overflow|underflow|access control|front[- ]running)",[cite: 17]
            r"(?:unsafe|insecure|dangerous)"[cite: 17]
        ],[cite: 17]
        FeedbackType.FEATURE_REQUEST: [[cite: 17]
            r"(?:add|implement|create|include)\s+(?:a|an)?\s+(?:new\s+)?(?:feature|functionality|capability)",[cite: 17]
            r"(?:need|want|require)\s+(?:to be able to|the ability to)"[cite: 17]
        ],[cite: 17]
        FeedbackType.BUG_REPORT: [[cite: 17]
            r"(?:bug|error|issue|problem|incorrect|wrong)",[cite: 17]
            r"(?:not working|failing|broken|malfunctioning)"[cite: 17]
        ],[cite: 17]
        FeedbackType.PERFORMANCE_ISSUE: [[cite: 17]
            r"(?:gas|performance|efficiency|optimization|cost)",[cite: 17]
            r"(?:expensive|slow|inefficient|high gas)"[cite: 17]
        ],[cite: 17]
        FeedbackType.STYLE_ISSUE: [[cite: 17]
            r"(?:style|format|indentation|naming|convention)",[cite: 17]
            r"(?:should be|could be)\s+(?:more|better)"[cite: 17]
        ],[cite: 17]
        FeedbackType.DOCUMENTATION: [[cite: 17]
            r"(?:documentation|comment|natspec|explain|describe)",[cite: 17]
            r"(?:comment|doc)\s+(?:block|string)"[cite: 17]
        ],[cite: 17]
        FeedbackType.ARCHITECTURE: [[cite: 17]
            r"(?:architecture|design|pattern|structure|refactor)",[cite: 17]
            r"(?:should|could)\s+(?:be)\s+(?:separated|extracted|refactored)"[cite: 17]
        ],[cite: 17]
        FeedbackType.TESTING: [[cite: 17]
            r"(?:test|coverage|assertion|mock|fixture)",[cite: 17]
            r"(?:test\s+should|test\s+case|test\s+scenario)"[cite: 17]
        ],[cite: 17]
        FeedbackType.DEPLOYMENT: [[cite: 17]
            r"(?:deploy|deployment|network|chain|contract)",[cite: 17]
            r"(?:constructor|init|initialize)"[cite: 17]
        ]
    }

    # Mapping des severites par defaut[cite: 17]
    DEFAULT_SEVERITY = {[cite: 17]
        FeedbackType.BUG_REPORT: FeedbackSeverity.CRITICAL,[cite: 17]
        FeedbackType.SECURITY_CONCERN: FeedbackSeverity.CRITICAL,[cite: 17]
        FeedbackType.PERFORMANCE_ISSUE: FeedbackSeverity.HIGH,[cite: 17]
        FeedbackType.ARCHITECTURE: FeedbackSeverity.HIGH,[cite: 17]
        FeedbackType.CODE_REVIEW: FeedbackSeverity.MEDIUM,[cite: 17]
        FeedbackType.TESTING: FeedbackSeverity.MEDIUM,[cite: 17]
        FeedbackType.DEPLOYMENT: FeedbackSeverity.MEDIUM,[cite: 17]
        FeedbackType.FEATURE_REQUEST: FeedbackSeverity.MEDIUM,[cite: 17]
        FeedbackType.DOCUMENTATION: FeedbackSeverity.LOW,[cite: 17]
        FeedbackType.STYLE_ISSUE: FeedbackSeverity.LOW,[cite: 17]
        FeedbackType.SUGGESTION: FeedbackSeverity.LOW,[cite: 17]
        FeedbackType.APPROVAL: FeedbackSeverity.LOW,[cite: 17]
        FeedbackType.CLARIFICATION: FeedbackSeverity.LOW,[cite: 17]
        FeedbackType.REJECTION: FeedbackSeverity.HIGH,[cite: 17]
        FeedbackType.CUSTOM: FeedbackSeverity.MEDIUM[cite: 17]
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
        Initialise l'Agent Feedback.[cite: 17]

        Args:[cite: 17]
            agent_id: Identifiant unique de l'agent[cite: 17]
            name: Nom de l'agent (defaut: "FeedbackAgent")[cite: 17]
            skills: Liste des competences (optionnel)[cite: 17]
            llm_client: Client LLM pour l'interpretation[cite: 17]
            knowledge_base: Base de connaissances RAG[cite: 17]
            best_practices: Bonnes pratiques a appliquer[cite: 17]
            max_loop_iterations: Nombre maximum d'iterations de retroaction[cite: 17]
            require_validation: Valider les modifications (defaut: True)[cite: 17]
            auto_apply_low_severity: Appliquer automatiquement les retours faibles[cite: 17]
        """
        super().__init__(agent_id=agent_id, name=name, skills=skills)[cite: 17]
        self.llm_client = llm_client[cite: 17]
        self.knowledge_base = knowledge_base[cite: 17]
        self.best_practices = best_practices or [][cite: 17]
        self.max_loop_iterations = max_loop_iterations[cite: 17]
        self.require_validation = require_validation[cite: 17]
        self.auto_apply_low_severity = auto_apply_low_severity[cite: 17]
        self._feedback_history: List[Feedback] = [][cite: 17]
        self._feedback_results: List[FeedbackResult] = [][cite: 17]
        self._feedback_loop_count = 0[cite: 17]

        logger.info(f"FeedbackAgent initialized: {agent_id}")[cite: 17]

    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse le retour humain et applique les modifications.[cite: 17]

        Args:[cite: 17]
            task_data: Doit contenir:[cite: 17]
                - 'feedback': Retour humain[cite: 17]
                - 'code': Code a modifier[cite: 17]
                - 'source': Source du retour (optionnel)[cite: 17]
                - 'context': Contexte du retour (optionnel)[cite: 17]
                - 'task_id': ID de la tache (optionnel)[cite: 17]

        Returns:[cite: 17]
            Dict contenant:[cite: 17]
            - 'status': SUCCESS ou FAILED[cite: 17]
            - 'result': FeedbackResult en dictionnaire[cite: 17]
            - 'code': Code modifie[cite: 17]
            - 'feedback_applied': Retours appliques[cite: 17]
            - 'feedback_ignored': Retours ignores[cite: 17]
        """
        start_time = datetime.utcnow()[cite: 17]

        try:
            # 1. Extraction des parametres[cite: 17]
            feedback_content = task_data.get("feedback", "")[cite: 17]
            code = task_data.get("code", "")[cite: 17]
            source = task_data.get("source", "tech_lead")[cite: 17]
            context = task_data.get("context", {})[cite: 17]

            if not feedback_content:
                raise ValueError("No feedback provided")[cite: 17]

            if not code:
                raise ValueError("No code provided")[cite: 17]

            # 2. Analyse du retour[cite: 17]
            feedback = await self._analyze_feedback(
                content=feedback_content,
                source=source,
                context=context
            )

            # 3. Sauvegarde du retour[cite: 17]
            self._feedback_history.append(feedback)

            # 4. Application du retour[cite: 17]
            result = await self._apply_feedback(
                feedback=feedback,
                code=code
            )

            # 5. Validation des modifications[cite: 17]
            if self.require_validation:
                result = await self._validate_result(result)

            # 6. Application des bonnes pratiques[cite: 17]
            if self.best_practices:
                result = await self._apply_best_practices(result)

            # 7. Persistance du resultat[cite: 17]
            self._feedback_results.append(result)

            # 8. Logging de l'execution[cite: 17]
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),
                prompt=f"Feedback from {source}: {feedback_content[:100]}...",
                response=f"Applied {len(result.feedback_applied)} changes",
                tool_output=json.dumps(result.to_dict(), indent=2)[:500]
            )

            logger.info(f"Feedback applied: {len(result.feedback_applied)} changes, passed={result.validation_passed}")[cite: 17]

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
            logger.error(f"FeedbackAgent execution failed: {str(e)}")[cite: 17]
            return {
                "status": "FAILED",
                "error": str(e),
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
            }

    # =========================================================================
    # ANALYSE DU RETOUR[cite: 17]
    # =========================================================================

    async def _analyze_feedback(
        self,
        content: str,
        source: str,
        context: Dict[str, Any]
    ) -> Feedback:
        """
        Analyse et structure le retour humain.[cite: 17]

        Args:[cite: 17]
            content: Contenu textuel du retour[cite: 17]
            source: Source du retour[cite: 17]
            context: Contexte du retour[cite: 17]

        Returns:[cite: 17]
            Feedback: Retour structure[cite: 17]
        """
        # 1. Determination du type[cite: 17]
        feedback_type = self._detect_feedback_type(content)

        # 2. Determination de la severite[cite: 17]
        severity = self._detect_feedback_severity(content, feedback_type)

        # 3. Extraction de la correction suggeree (si presente)[cite: 17]
        suggested_fix = await self._extract_suggested_fix(content, context)

        # 4. Creation du retour[cite: 17]
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

        logger.info(f"Feedback analyzed: type={feedback_type.value}, severity={severity.value}")[cite: 17]

        return feedback

    def _detect_feedback_type(self, content: str) -> FeedbackType:
        """
        Detecte le type de retour.[cite: 17]

        Args:[cite: 17]
            content: Contenu textuel[cite: 17]

        Returns:[cite: 17]
            FeedbackType: Type detecte[cite: 17]
        """
        content_lower = content.lower()[cite: 17]

        # Detection par patterns[cite: 17]
        for feedback_type, patterns in self.FEEDBACK_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, content_lower, re.IGNORECASE):
                    return feedback_type

        # Detection par mots-cles[cite: 17]
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

        return FeedbackType.CUSTOM[cite: 17]

    def _detect_feedback_severity(
        self,
        content: str,
        feedback_type: FeedbackType
    ) -> FeedbackSeverity:
        """
        Detecte la severite du retour.[cite: 17]

        Args:[cite: 17]
            content: Contenu textuel[cite: 17]
            feedback_type: Type de retour[cite: 17]

        Returns:[cite: 17]
            FeedbackSeverity: Severite detectee[cite: 17]
        """
        content_lower = content.lower()[cite: 17]

        # Mots-cles de severite[cite: 17]
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

        # Severite par defaut selon le type[cite: 17]
        return self.DEFAULT_SEVERITY.get(feedback_type, FeedbackSeverity.MEDIUM)

    async def _extract_suggested_fix(
        self,
        content: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extrait une correction suggeree du retour.[cite: 17]

        Args:[cite: 17]
            content: Contenu textuel[cite: 17]
            context: Contexte[cite: 17]

        Returns:[cite: 17]
            Optional[str]: Correction suggeree ou None[cite: 17]
        """
        # Recherche de blocs de code[cite: 17]
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", content)
        if code_blocks:
            return code_blocks[0].strip()

        # Recherche de suggestions explicites[cite: 17]
        patterns = [
            r"(?:suggest|recommend|propose)\s+(?:using|to use|changing\s+to)\s+`([^`]+)`",
            r"(?:fix|change|update)\s+to\s+`([^`]+)`",
            r"(?:should\s+be|must\s+be)\s+`([^`]+)`"
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1)

        # Si LLM disponible, tenter d'extraire une correction[cite: 17]
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
                logger.warning(f"Failed to extract fix via LLM: {str(e)}")[cite: 17]

        return None

    # =========================================================================
    # APPLICATION DU RETOUR[cite: 17]
    # =========================================================================

    async def _apply_feedback(
        self,
        feedback: Feedback,
        code: str
    ) -> FeedbackResult:
        """
        Applique le retour au code de manière robuste avec support de secours.

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
        fix_applied = False

        # 1. Auto-application pour les retours de severite faible si fix suggéré
        if self.auto_apply_low_severity and feedback.severity in [
            FeedbackSeverity.LOW, FeedbackSeverity.SUGGESTION
        ] and feedback.suggested_fix:
            modified_code = await self._apply_fix(modified_code, feedback.suggested_fix)
            if modified_code != original_code:
                applied.append(feedback.id)
                changes.append({
                    "type": "auto_apply",
                    "feedback_id": feedback.id,
                    "change": "Applied suggested fix automatically"
                })
                fix_applied = True

        # 2. Pour les retours plus severes, utilisation du LLM
        if not fix_applied and self.llm_client and feedback.severity in [
            FeedbackSeverity.MEDIUM, FeedbackSeverity.HIGH,
            FeedbackSeverity.CRITICAL, FeedbackSeverity.BLOCKING, FeedbackSeverity.CUSTOM
        ]:
            try:
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

                extracted_code = self._extract_code_from_response(response) if response else ""

                if extracted_code and extracted_code != code:
                    modified_code = extracted_code
                    applied.append(feedback.id)
                    changes.append({
                        "type": "llm_apply",
                        "feedback_id": feedback.id,
                        "change": "Applied via LLM"
                    })
                    fix_applied = True

            except Exception as e:
                logger.error(f"LLM application failed: {str(e)}")[cite: 17]

        # 3. Fallback: si le LLM n'est pas disponible ou a échoué mais qu'un suggested_fix existe
        if not fix_applied and feedback.suggested_fix:
            modified_code = await self._apply_fix(modified_code, feedback.suggested_fix)
            if modified_code != original_code:
                applied.append(feedback.id)
                changes.append({
                    "type": "suggested_fix_fallback",
                    "feedback_id": feedback.id,
                    "change": "Applied suggested fix as fallback"
                })
                fix_applied = True

        if not fix_applied:
            ignored.append(feedback.id)
            changes.append({
                "type": "manual_required",
                "feedback_id": feedback.id,
                "message": "Manual application required or no valid fix could be applied"
            })

        # Mise a jour du feedback[cite: 17]
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
        Applique un correctif spécifique de manière robuste sans corrompre le fichier complet.

        Args:
            code: Code original
            fix: Correctif a appliquer

        Returns:
            str: Code modifie
        """
        if not fix:
            return code

        # Si le fix est un code complet (ex: contrat ou pragma complet)
        if "pragma solidity" in fix or "contract " in fix:
            return fix

        # Tentative de remplacement de fonction ciblée si le fix contient une fonction
        func_matches = re.findall(r"function\s+(\w+)", fix)
        if func_matches:
            for func_name in func_matches:
                pattern = rf"function\s+{func_name}\s*\([^)]*\)[^{{]*\{{(?:[^{{}}]|{{(?:[^{{}}]|{{[^}}]*}})*}})*\}}"
                if re.search(pattern, code):
                    return re.sub(pattern, fix, code, count=1)

        return code

    def _extract_code_from_response(self, response: str) -> str:
        """
        Extrait le code de la reponse du LLM.[cite: 17]

        Args:[cite: 17]
            response: Reponse du LLM[cite: 17]

        Returns:[cite: 17]
            str: Code extrait[cite: 17]
        """
        code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]*?)```", response)
        if code_blocks:
            return code_blocks[0].strip()
        return response.strip()

    # =========================================================================
    # VALIDATION[cite: 17]
    # =========================================================================

    async def _validate_result(self, result: FeedbackResult) -> FeedbackResult:
        """
        Valide le resultat de l'application.[cite: 17]

        Args:[cite: 17]
            result: Resultat a valider[cite: 17]

        Returns:[cite: 17]
            FeedbackResult: Resultat valide[cite: 17]
        """
        errors = [][cite: 17]

        # Validation basique[cite: 17]
        if not result.modified_code:
            errors.append("Modified code is empty")[cite: 17]
            result.validation_passed = False[cite: 17]

        if result.modified_code == result.original_code and result.feedback_applied:
            errors.append("Code unchanged despite feedback application")[cite: 17]
            result.validation_passed = False[cite: 17]

        # Validation syntaxique simplifiee[cite: 17]
        if result.modified_code:
            if "pragma solidity" not in result.modified_code and "contract" not in result.modified_code:
                if "function" not in result.modified_code:
                    errors.append("Invalid Solidity code structure")[cite: 17]
                    result.validation_passed = False[cite: 17]

        result.validation_errors = errors[cite: 17]

        # Calcul du score de qualite[cite: 17]
        result.quality_score = self._calculate_quality_score(result)[cite: 17]

        return result

    def _calculate_quality_score(self, result: FeedbackResult) -> float:
        """
        Calcule le score de qualite.[cite: 17]

        Args:[cite: 17]
            result: Resultat de l'application[cite: 17]

        Returns:[cite: 17]
            float: Score de qualite (0-100)[cite: 17]
        """
        score = 100.0[cite: 17]

        # Deductions[cite: 17]
        if not result.validation_passed:
            score -= 30.0[cite: 17]

        if len(result.feedback_ignored) > 0:
            score -= len(result.feedback_ignored) * 5.0[cite: 17]

        if result.feedback_applied and result.modified_code == result.original_code:
            score -= 20.0[cite: 17]

        # Bonus[cite: 17]
        if result.feedback_applied:
            score += 10.0[cite: 17]

        return max(0.0, min(100.0, score))[cite: 17]

    async def _apply_best_practices(self, result: FeedbackResult) -> FeedbackResult:
        """
        Applique les bonnes pratiques au resultat.[cite: 17]

        Args:[cite: 17]
            result: Resultat de l'application[cite: 17]

        Returns:[cite: 17]
            FeedbackResult: Resultat ameliore[cite: 17]
        """
        for practice in self.best_practices:
            try:
                validation = await practice.validate({"code": result.modified_code})[cite: 17]
                if not validation.get("passed", True):
                    # Application des corrections suggerees[cite: 17]
                    for violation in validation.get("violations", []):
                        if "suggestion" in violation:
                            result.changes.append({
                                "type": "best_practice",
                                "violation": violation.get("rule_name"),
                                "suggestion": violation.get("suggestion")
                            })
                    result.quality_score = min(result.quality_score, validation.get("score", 100))[cite: 17]
            except Exception as e:
                logger.warning(f"Best practice validation failed: {str(e)}")[cite: 17]

        return result

    # =========================================================================
    # HISTORIQUE ET STATISTIQUES[cite: 17]
    # =========================================================================

    def get_feedback_history(
        self,
        limit: Optional[int] = None,
        feedback_type: Optional[FeedbackType] = None,
        severity: Optional[FeedbackSeverity] = None
    ) -> List[Feedback]:
        """
        Recupere l'historique des retours avec filtres.[cite: 17]

        Args:[cite: 17]
            limit: Nombre maximum de retours[cite: 17]
            feedback_type: Filtrer par type[cite: 17]
            severity: Filtrer par severite[cite: 17]

        Returns:[cite: 17]
            List[Feedback]: Historique des retours[cite: 17]
        """
        result = self._feedback_history[cite: 17]

        if feedback_type:
            result = [f for f in result if f.type == feedback_type][cite: 17]

        if severity:
            result = [f for f in result if f.severity == severity][cite: 17]

        if limit:
            result = result[-limit:][cite: 17]

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.[cite: 17]

        Returns:[cite: 17]
            Dict: Statistiques detaillees[cite: 17]
        """
        total_feedback = len(self._feedback_history)[cite: 17]
        applied_feedback = sum(1 for f in self._feedback_history if f.applied)[cite: 17]

        by_type = {}[cite: 17]
        by_severity = {}[cite: 17]

        for f in self._feedback_history:
            by_type[f.type.value] = by_type.get(f.type.value, 0) + 1[cite: 17]
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1[cite: 17]

        return {
            "total_feedback": total_feedback,
            "applied_feedback": applied_feedback,
            "applied_rate": applied_feedback / total_feedback if total_feedback > 0 else 0,
            "by_type": by_type,
            "by_severity": by_severity,
            "total_results": len(self._feedback_results),
            "average_quality_score": sum(r.quality_score for r in self._feedback_results) / len(self._feedback_results) if self._feedback_results else 0,
            "feedback_loop_count": self._feedback_loop_count
        }

    # =========================================================================
    # REPRESENTATION[cite: 17]
    # =========================================================================

    def __repr__(self) -> str:
        return f"<FeedbackAgent(agent_id='{self.agent_id}', feedback={len(self._feedback_history)})>"[cite: 17]

    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.[cite: 17]

        Returns:[cite: 17]
            Dict: Representation de l'agent[cite: 17]
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
            "auto_apply_low_severity": self.auto_apply_low_severity
        }

    # =========================================================================
    # INTERACTION AVEC L'HUMAIN (HITL)[cite: 17]
    # =========================================================================

    async def request_clarification(
        self,
        feedback: Feedback,
        questions: List[str]
    ) -> Dict[str, Any]:
        """
        Demande une clarification a l'humain.[cite: 17]

        Args:[cite: 17]
            feedback: Retour necessitant clarification[cite: 17]
            questions: Questions a poser[cite: 17]

        Returns:[cite: 17]
            Dict: Demande de clarification[cite: 17]
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
        Genere un resume des retours.[cite: 17]

        Returns:[cite: 17]
            str: Resume des retours[cite: 17]
        """
        if not self._feedback_history:
            return "No feedback received."[cite: 17]

        lines = [
            "📊 Feedback Summary",
            "=" * 40,
            f"Total feedback: {len(self._feedback_history)}",
            f"Applied: {sum(1 for f in self._feedback_history if f.applied)}",
            f"Pending: {sum(1 for f in self._feedback_history if not f.applied)}",
            "",
            "📌 By Type:"
        ]

        by_type = {}[cite: 17]
        for f in self._feedback_history:
            by_type[f.type.value] = by_type.get(f.type.value, 0) + 1[cite: 17]

        for type_name, count in sorted(by_type.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - {type_name}: {count}")[cite: 17]

        lines.append("")[cite: 17]
        lines.append("📌 By Severity:")[cite: 17]

        by_severity = {}[cite: 17]
        for f in self._feedback_history:
            by_severity[f.severity.value] = by_severity.get(f.severity.value, 0) + 1[cite: 17]

        for sev, count in sorted(by_severity.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"  - {sev}: {count}")[cite: 17]

        if self._feedback_history:
            lines.append("")[cite: 17]
            lines.append("📌 Recent Feedback:")[cite: 17]
            for f in self._feedback_history[-3:]:
                lines.append(f"  - [{f.type.value}] {f.content[:100]}...")[cite: 17]

        return "\n".join(lines)[cite: 17]