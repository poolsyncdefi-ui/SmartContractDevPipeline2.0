# src/agents/templates/architect_agent.py[cite: 15]

"""
Architect agent for the Smart Contract Dev Pipeline.
F19 – src/agents/templates/architect_agent.py

Rôle Fonctionnel : Agent architecte analysant les specifications et concevant le DAG.
L'Agent Architecte est le premier agent du pipeline. Il est responsable de:
- L'analyse des specifications du projet (YAML)
- La decomposition du projet en taches (DAG)
- L'identification des competences requises
- La creation dynamique de nouvelles competences si necessaires
- La generation du workflow complet pour les autres agents

Cet agent agit comme le coordinateur principal du pipeline,
assurant que toutes les taches sont correctement definies et
que les competences necessaires sont disponibles.
"""
from src.agents.base.abstract_agent import AbstractAgent[cite: 15]
from typing import Dict, Any, List, Optional, Set, Tuple[cite: 15]
from datetime import datetime[cite: 15]
import yaml[cite: 15]
import json[cite: 15]
import logging[cite: 15]
import re[cite: 15]
from enum import Enum[cite: 15]
from dataclasses import dataclass, field[cite: 15]

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError, SkillNotFoundError[cite: 15]
from src.core.models import ProjectConfig, Skill[cite: 15]
from src.agents.factory.skill_registry import SkillRegistry, SkillMetadata, SkillScope[cite: 15]
from src.persistence.knowledge_base import KnowledgeBase[cite: 15]

# Configuration du logging
logger = logging.getLogger(__name__)[cite: 15]


class TaskType(str, Enum):
    """
    Types de taches possibles dans le DAG.
    """
    ANALYSIS = "analysis"[cite: 15]
    DESIGN = "design"[cite: 15]
    CONTRACT_GENERATION = "contract_generation"[cite: 15]
    TEST_GENERATION = "test_generation"[cite: 15]
    SECURITY_AUDIT = "security_audit"[cite: 15]
    FORMAL_VERIFICATION = "formal_verification"[cite: 15]
    OPTIMIZATION = "optimization"[cite: 15]
    DEPLOYMENT = "deployment"[cite: 15]
    DOCUMENTATION = "documentation"[cite: 15]
    REVIEW = "review"[cite: 15]
    CUSTOM = "custom"[cite: 15]


class TaskStatus(str, Enum):
    """
    Statuts possibles pour une tache dans le DAG.
    """
    PENDING = "pending"[cite: 15]
    READY = "ready"[cite: 15]
    IN_PROGRESS = "in_progress"[cite: 15]
    COMPLETED = "completed"[cite: 15]
    FAILED = "failed"[cite: 15]
    BLOCKED = "blocked"[cite: 15]
    SKIPPED = "skipped"[cite: 15]


@dataclass
class TaskNode:
    """
    Nœud de tache dans le DAG.
    
    Attributes:
        task_id (str): Identifiant unique de la tache
        name (str): Nom descriptif de la tache
        task_type (TaskType): Type de la tache
        description (str): Description detaillee
        skills_required (List[str]): Competences requises
        dependencies (List[str]): IDs des taches precedentes
        parameters (Dict): Parametres de la tache
        status (TaskStatus): Statut actuel
        priority (int): Priorite (1-10, 10 = plus eleve)
        estimated_duration (float): Duree estimee en heures
        assigned_agent (Optional[str]): ID de l'agent assigne
        created_at (datetime): Date de creation
        updated_at (datetime): Date de mise a jour
        metadata (Dict): Metadonnees supplementaires
    """
    task_id: str[cite: 15]
    name: str[cite: 15]
    task_type: TaskType[cite: 15]
    description: str = ""[cite: 15]
    skills_required: List[str] = field(default_factory=list)[cite: 15]
    dependencies: List[str] = field(default_factory=list)[cite: 15]
    parameters: Dict[str, Any] = field(default_factory=dict)[cite: 15]
    status: TaskStatus = TaskStatus.PENDING[cite: 15]
    priority: int = 5[cite: 15]
    estimated_duration: float = 0.0[cite: 15]
    assigned_agent: Optional[str] = None[cite: 15]
    created_at: datetime = field(default_factory=datetime.utcnow)[cite: 15]
    updated_at: datetime = field(default_factory=datetime.utcnow)[cite: 15]
    metadata: Dict[str, Any] = field(default_factory=dict)[cite: 15]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit le nœud en dictionnaire."""
        return {
            "task_id": self.task_id,[cite: 15]
            "name": self.name,[cite: 15]
            "task_type": self.task_type.value,[cite: 15]
            "description": self.description,[cite: 15]
            "skills_required": self.skills_required,[cite: 15]
            "dependencies": self.dependencies,[cite: 15]
            "parameters": self.parameters,[cite: 15]
            "status": self.status.value,[cite: 15]
            "priority": self.priority,[cite: 15]
            "estimated_duration": self.estimated_duration,[cite: 15]
            "assigned_agent": self.assigned_agent,[cite: 15]
            "created_at": self.created_at.isoformat() if self.created_at else None,[cite: 15]
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,[cite: 15]
            "metadata": self.metadata[cite: 15]
        }


@dataclass
class ProjectAnalysis:
    """
    Resultat de l'analyse d'un projet.
    
    Attributes:
        project_id (str): ID du projet
        name (str): Nom du projet
        description (str): Description du projet
        version (str): Version du projet
        chain (str): Blockchain cible
        complexity_score (int): Score de complexite (1-10)
        total_tasks (int): Nombre total de taches
        tasks (List[TaskNode]): Liste des taches
        skills_required (Set[str]): Competences requises
        missing_skills (Set[str]): Competences manquantes
        estimated_duration (float): Duree totale estimee
        created_at (datetime): Date de creation
        metadata (Dict): Metadonnees supplementaires
    """
    project_id: str[cite: 15]
    name: str[cite: 15]
    description: str = ""[cite: 15]
    version: str = "1.0.0"[cite: 15]
    chain: str = "ethereum"[cite: 15]
    complexity_score: int = 1[cite: 15]
    total_tasks: int = 0[cite: 15]
    tasks: List[TaskNode] = field(default_factory=list)[cite: 15]
    skills_required: Set[str] = field(default_factory=set)[cite: 15]
    missing_skills: Set[str] = field(default_factory=set)[cite: 15]
    estimated_duration: float = 0.0[cite: 15]
    created_at: datetime = field(default_factory=datetime.utcnow)[cite: 15]
    metadata: Dict[str, Any] = field(default_factory=dict)[cite: 15]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit l'analyse en dictionnaire."""
        return {
            "project_id": self.project_id,[cite: 15]
            "name": self.name,[cite: 15]
            "description": self.description,[cite: 15]
            "version": self.version,[cite: 15]
            "chain": self.chain,[cite: 15]
            "complexity_score": self.complexity_score,[cite: 15]
            "total_tasks": self.total_tasks,[cite: 15]
            "tasks": [t.to_dict() for t in self.tasks],[cite: 15]
            "skills_required": list(self.skills_required),[cite: 15]
            "missing_skills": list(self.missing_skills),[cite: 15]
            "estimated_duration": self.estimated_duration,[cite: 15]
            "created_at": self.created_at.isoformat() if self.created_at else None,[cite: 15]
            "metadata": self.metadata[cite: 15]
        }


class ArchitectAgent(AbstractAgent):
    """
    Agent specialise dans l'architecture et l'orchestration.
    
    L'ArchitectAgent analyse les specifications du projet, decompose
    les requirements en taches executables et planifie le workflow
    complet pour le pipeline.
    
    Attributes:
        skill_registry (SkillRegistry): Registre des competences
        knowledge_base (Optional[KnowledgeBase]): Base de connaissances
        max_tasks (int): Nombre maximum de taches par DAG
        auto_create_skills (bool): Creer automatiquement les competences manquantes
    """
    
    def __init__(
        self,
        agent_id: str,
        name: str = "ArchitectAgent",
        skills: Optional[List] = None,
        llm_client = None,
        knowledge_base: Optional[KnowledgeBase] = None,
        skill_registry: Optional[SkillRegistry] = None,
        max_tasks: int = 100,
        auto_create_skills: bool = True
    ):
        """
        Initialise l'Agent Architecte.
        
        Args:
            agent_id: Identifiant unique de l'agent
            name: Nom de l'agent (defaut: "ArchitectAgent")
            skills: Liste des competences (optionnel)
            llm_client: Client LLM pour les appels IA (optionnel)
            knowledge_base: Base de connaissances pour le RAG (optionnel)
            skill_registry: Registre des competences (optionnel)
            max_tasks: Nombre maximum de taches par DAG (defaut: 100)
            auto_create_skills: Creer automatiquement les competences manquantes
        """
        super().__init__(agent_id=agent_id, name=name, skills=skills, llm_client=llm_client)[cite: 15]
        self.knowledge_base = knowledge_base[cite: 15]
        self.skill_registry = skill_registry or SkillRegistry()[cite: 15]
        self.max_tasks = max_tasks[cite: 15]
        self.auto_create_skills = auto_create_skills[cite: 15]
        self._analysis_history: List[ProjectAnalysis] = [][cite: 15]
        
        logger.info(f"ArchitectAgent initialized: {agent_id}")[cite: 15]
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyse la specification et genere le DAG.
        
        Args:
            task_data: Doit contenir:
                - 'yaml_content': Contenu YAML de la specification
                - 'project_id': ID du projet (optionnel)
                - 'project_name': Nom du projet (optionnel)
                
        Returns:
            Dict contenant:
            - 'status': SUCCESS ou FAILED
            - 'analysis': ProjectAnalysis en dictionnaire
            - 'dag': Liste des taches
            - 'skills_required': Competences requises
            - 'missing_skills': Competences manquantes
        """
        start_time = datetime.utcnow()[cite: 15]
        
        try:
            # 1. Extraction des donnees
            yaml_content = task_data.get("yaml_content", "")[cite: 15]
            project_id = task_data.get("project_id", f"proj_{datetime.utcnow().timestamp()}")[cite: 15]
            project_name = task_data.get("project_name", "Unnamed Project")[cite: 15]
            
            if not yaml_content:
                raise ValueError("No yaml_content provided")[cite: 15]
            
            # 2. Parsing de la specification YAML
            spec = self.parse_yaml_spec(yaml_content)[cite: 15]
            if not spec:
                raise ValueError("Invalid or empty YAML specification")[cite: 15]
            
            # 3. Validation de la specification
            self._validate_spec(spec)[cite: 15]
            
            # 4. Analyse de la complexite
            complexity = self._analyze_complexity(spec)[cite: 15]
            
            # 5. Generation du DAG
            dag = await self.generate_dag(spec, project_id)[cite: 15]
            
            # 6. Extraction des competences requises
            skills_required = self._extract_skills(spec, dag)[cite: 15]
            
            # 7. Verification des competences disponibles
            missing_skills = self._check_available_skills(skills_required)[cite: 15]
            
            # 8. Creation dynamique des competences manquantes (FIXED: tracked initial count)
            initial_missing_count = len(missing_skills)
            if missing_skills and self.auto_create_skills:
                missing_skills = await self._create_missing_skills(missing_skills, spec)[cite: 15]
            
            # 9. Construction de l'analyse
            analysis = ProjectAnalysis(
                project_id=project_id,[cite: 15]
                name=project_name,[cite: 15]
                description=spec.get("description", ""),[cite: 15]
                version=spec.get("version", "1.0.0"),[cite: 15]
                chain=spec.get("chain", "ethereum"),[cite: 15]
                complexity_score=complexity,[cite: 15]
                total_tasks=len(dag),[cite: 15]
                tasks=dag,[cite: 15]
                skills_required=skills_required,[cite: 15]
                missing_skills=missing_skills,[cite: 15]
                estimated_duration=sum(t.estimated_duration for t in dag),[cite: 15]
                metadata={
                    "analysis_time": (datetime.utcnow() - start_time).total_seconds(),[cite: 15]
                    "yaml_size": len(yaml_content),[cite: 15]
                    "auto_created_skills": initial_missing_count - len(missing_skills)
                }
            )
            
            # 10. Persistance de l'analyse
            self._analysis_history.append(analysis)[cite: 15]
            
            # 11. Logging de l'execution
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),[cite: 15]
                prompt=yaml_content[:500],  # Log partiel[cite: 15]
                response=f"Generated {len(dag)} tasks",[cite: 15]
                tool_output=json.dumps(analysis.to_dict(), indent=2)[:500][cite: 15]
            )
            
            logger.info(f"Architect analysis complete: {len(dag)} tasks, {len(skills_required)} skills required")[cite: 15]
            
            return {
                "status": "SUCCESS",[cite: 15]
                "analysis": analysis.to_dict(),[cite: 15]
                "dag": [t.to_dict() for t in dag],[cite: 15]
                "skills_required": list(skills_required),[cite: 15]
                "missing_skills": list(missing_skills),[cite: 15]
                "complexity_score": complexity,[cite: 15]
                "estimated_duration": analysis.estimated_duration,[cite: 15]
                "metadata": {
                    "execution_time": (datetime.utcnow() - start_time).total_seconds()[cite: 15]
                }
            }
            
        except Exception as e:
            logger.error(f"ArchitectAgent execution failed: {str(e)}")[cite: 15]
            return {
                "status": "FAILED",[cite: 15]
                "error": str(e),[cite: 15]
                "execution_time": (datetime.utcnow() - start_time).total_seconds()[cite: 15]
            }
    
    # =========================================================================
    # ANALYSE ET PARSING
    # =========================================================================
    
    def parse_yaml_spec(self, yaml_text: str) -> Dict[str, Any]:
        """
        Parse la specification YAML avec gestion d'erreurs.
        
        Args:
            yaml_text: Texte YAML a parser
            
        Returns:
            Dict: Specification parsee ou dictionnaire vide
        """
        try:
            spec = yaml.safe_load(yaml_text)[cite: 15]
            if not spec:
                logger.warning("Empty YAML specification")[cite: 15]
                return {}[cite: 15]
            return spec[cite: 15]
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {str(e)}")[cite: 15]
            raise ValueError(f"Invalid YAML: {str(e)}")[cite: 15]
        except Exception as e:
            logger.error(f"Unexpected error parsing YAML: {str(e)}")[cite: 15]
            raise[cite: 15]
    
    def _validate_spec(self, spec: Dict[str, Any]) -> None:
        """
        Valide la specification du projet.
        
        Args:
            spec: Specification a valider
            
        Raises:
            ValueError: Si la specification est invalide
        """
        # Verification des champs obligatoires
        if "project" not in spec and "name" not in spec:
            raise ValueError("Project 'name' is required")[cite: 15]
        
        # Verification de la structure des taches
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or spec.get("workflow")[cite: 15]
        if not tasks:
            raise ValueError("No tasks or workflow defined in specification")[cite: 15]
        
        if not isinstance(tasks, list):
            raise ValueError("Tasks must be a list")[cite: 15]
        
        if len(tasks) > self.max_tasks:
            raise ValueError(f"Too many tasks ({len(tasks)} > {self.max_tasks})")[cite: 15]
        
        # Validation des taches individuelles
        for i, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise ValueError(f"Task {i} must be a dictionary")
            if "id" not in task and "name" not in task:
                raise ValueError(f"Task {i} missing 'id' or 'name'")[cite: 15]
            if "type" not in task:
                raise ValueError(f"Task {i} missing 'type'")[cite: 15]
        
        logger.debug(f"Spec validation passed: {len(tasks)} tasks")[cite: 15]
    
    def _analyze_complexity(self, spec: Dict[str, Any]) -> int:
        """
        Analyse la complexite du projet.
        
        Args:
            spec: Specification du projet
            
        Returns:
            int: Score de complexite (1-10)
        """
        score = 1[cite: 15]
        
        # Facteurs de complexite (FIXED: included "workflow" for consistency)
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or spec.get("workflow") or []
        num_tasks = len(tasks)[cite: 15]
        
        # Nombre de taches
        if num_tasks > 20:
            score += 3[cite: 15]
        elif num_tasks > 10:
            score += 2[cite: 15]
        elif num_tasks > 5:
            score += 1[cite: 15]
        
        # Types de taches
        task_types = [t.get("type", "").lower() for t in tasks if isinstance(t, dict)][cite: 15]
        if "security_audit" in task_types or "formal_verification" in task_types:
            score += 2[cite: 15]
        if "deployment" in task_types:
            score += 1[cite: 15]
        
        # Integrations
        integrations = spec.get("integrations", [])[cite: 15]
        if integrations:
            score += len(integrations)[cite: 15]
        
        # Dependances
        has_dependencies = any(t.get("dependencies") for t in tasks if isinstance(t, dict))[cite: 15]
        if has_dependencies:
            score += 1[cite: 15]
        
        return min(10, max(1, score))[cite: 15]
    
    # =========================================================================
    # GENERATION DU DAG
    # =========================================================================
    
    async def generate_dag(
        self,
        spec: Dict[str, Any],
        project_id: str
    ) -> List[TaskNode]:
        """
        Genere le DAG (Directed Acyclic Graph) des taches.
        
        Args:
            spec: Specification du projet
            project_id: ID du projet
            
        Returns:
            List[TaskNode]: Liste des nœuds de taches
        """
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or spec.get("workflow", [])[cite: 15]
        dag = [][cite: 15]
        task_map = {}[cite: 15]
        
        # Construction des nœuds
        for i, task_spec in enumerate(tasks):
            if not isinstance(task_spec, dict):
                continue
            task_id = task_spec.get("id") or task_spec.get("name", f"task_{i}")[cite: 15]
            
            # Determination du type
            task_type_str = task_spec.get("type", "custom").lower()[cite: 15]
            try:
                task_type = TaskType(task_type_str)[cite: 15]
            except ValueError:
                task_type = TaskType.CUSTOM[cite: 15]
                logger.warning(f"Unknown task type '{task_type_str}' for {task_id}, using CUSTOM")[cite: 15]
            
            # Extraction des competences requises
            skills = self._extract_task_skills(task_spec)[cite: 15]
            
            # Extraction des dependances (FIXED: robustness for null/non-list)
            deps = task_spec.get("dependencies") or [][cite: 15]
            if not isinstance(deps, list):
                deps = [deps] if deps else []
            
            # Creation du nœud
            node = TaskNode(
                task_id=task_id,[cite: 15]
                name=task_spec.get("name", task_id),[cite: 15]
                task_type=task_type,[cite: 15]
                description=task_spec.get("description", ""),[cite: 15]
                skills_required=skills,[cite: 15]
                dependencies=deps,[cite: 15]
                parameters=task_spec.get("parameters", {}) or {},[cite: 15]
                priority=task_spec.get("priority", 5),[cite: 15]
                estimated_duration=task_spec.get("estimated_duration", 0.0),[cite: 15]
                metadata={
                    "source": task_spec,[cite: 15]
                    "index": i[cite: 15]
                }
            )
            
            dag.append(node)[cite: 15]
            task_map[task_id] = node[cite: 15]
        
        # Validation des dependances (cycles)
        self._validate_dag(dag)[cite: 15]
        
        # Tri topologique des taches
        sorted_dag = self._topological_sort(dag)[cite: 15]
        
        # Enrichissement avec le contexte RAG
        if self.knowledge_base:
            enriched_dag = await self._enrich_with_context(sorted_dag, spec)[cite: 15]
            return enriched_dag[cite: 15]
        
        return sorted_dag[cite: 15]
    
    def _validate_dag(self, dag: List[TaskNode]) -> None:
        """
        Valide le DAG pour eviter les cycles.
        
        Args:
            dag: Liste des nœuds de taches
            
        Raises:
            ValueError: Si un cycle est detecte
        """
        # Construction du graphe
        graph = {node.task_id: node.dependencies for node in dag}[cite: 15]
        
        # Detection des cycles avec DFS
        visited = set()[cite: 15]
        rec_stack = set()[cite: 15]
        
        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)[cite: 15]
            rec_stack.add(node_id)[cite: 15]
            
            for dep in graph.get(node_id, []):
                if dep not in visited:
                    if has_cycle(dep):
                        return True[cite: 15]
                elif dep in rec_stack:
                    return True[cite: 15]
            
            rec_stack.remove(node_id)[cite: 15]
            return False[cite: 15]
        
        for node_id in graph:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise ValueError(f"Cycle detected in DAG involving node {node_id}")[cite: 15]
        
        # Verification des dependances existantes
        all_task_ids = {node.task_id for node in dag}[cite: 15]
        for node in dag:
            for dep in node.dependencies:
                if dep not in all_task_ids:
                    raise ValueError(f"Task {node.task_id} depends on {dep} which does not exist")[cite: 15]
        
        logger.debug(f"DAG validation passed: {len(dag)} tasks, no cycles")[cite: 15]
    
    def _topological_sort(self, dag: List[TaskNode]) -> List[TaskNode]:
        """
        Tri topologique des taches (Kahn's algorithm).
        
        Args:
            dag: Liste des nœuds de taches
            
        Returns:
            List[TaskNode]: Taches triees topologiquement
        """
        from collections import deque[cite: 15]
        
        # Construction du graphe
        task_map = {node.task_id: node for node in dag}[cite: 15]
        in_degree = {node.task_id: 0 for node in dag}[cite: 15]
        graph = {node.task_id: [] for node in dag}[cite: 15]
        
        for node in dag:
            for dep in node.dependencies:
                if dep in task_map:
                    graph[dep].append(node.task_id)[cite: 15]
                    in_degree[node.task_id] += 1[cite: 15]
        
        # File des taches sans dependances
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])[cite: 15]
        sorted_tasks = [][cite: 15]
        
        while queue:
            tid = queue.popleft()[cite: 15]
            sorted_tasks.append(task_map[tid])[cite: 15]
            
            for next_tid in graph.get(tid, []):
                in_degree[next_tid] -= 1[cite: 15]
                if in_degree[next_tid] == 0:
                    queue.append(next_tid)[cite: 15]
        
        # Verification: tous les nœuds sont-ils inclus?
        if len(sorted_tasks) != len(dag):
            logger.warning("Topological sort incomplete - possible cycle or missing nodes")[cite: 15]
            # Retourner l'ordre original en cas de probleme
            return dag[cite: 15]
        
        return sorted_tasks[cite: 15]
    
    async def _enrich_with_context(
        self,
        dag: List[TaskNode],
        spec: Dict[str, Any]
    ) -> List[TaskNode]:
        """
        Enrichit le DAG avec le contexte RAG.
        
        Args:
            dag: Liste des nœuds de taches
            spec: Specification du projet
            
        Returns:
            List[TaskNode]: DAG enrichi
        """
        if not self.knowledge_base:
            return dag[cite: 15]
        
        try:
            # Construction de la requete
            query = f"Smart contract development: {spec.get('name', '')} {spec.get('description', '')}"[cite: 15]
            context_docs = self.knowledge_base.query_context(query, n_results=3)[cite: 15]
            
            if context_docs:
                # Enrichissement des taches avec le contexte
                for node in dag:
                    if not hasattr(node, 'metadata') or node.metadata is None:
                        node.metadata = {}[cite: 15]
                    node.metadata['rag_context'] = context_docs[cite: 15]
                    
                    # Amelioration des descriptions avec le contexte
                    if context_docs and len(context_docs) > 0:
                        node.description += f"\n\nContext: {context_docs[0][:200]}..."[cite: 15]
                
                logger.info(f"DAG enriched with {len(context_docs)} RAG documents")[cite: 15]
        
        except Exception as e:
            logger.warning(f"RAG enrichment failed: {str(e)}")[cite: 15]
        
        return dag[cite: 15]
    
    # =========================================================================
    # EXTRACTION DES COMPETENCES
    # =========================================================================
    
    def _extract_skills(self, spec: Dict[str, Any], dag: List[TaskNode]) -> Set[str]:
        """
        Extrait toutes les competences requises du projet.
        
        Args:
            spec: Specification du projet
            dag: DAG des taches
            
        Returns:
            Set[str]: Ensemble des competences requises
        """
        skills = set()[cite: 15]
        
        # 0. Competences de niveau racine (FIXED: added support for root-level specs)
        root_skills = spec.get("skills_required") or spec.get("skills", [])
        if isinstance(root_skills, list):
            for skill in root_skills:
                if isinstance(skill, str):
                    skills.add(skill)
                elif isinstance(skill, dict):
                    s_name = skill.get("name") or skill.get("skill")
                    if s_name:
                        skills.add(s_name)
        
        # 1. Competences explicites dans les requirements de l'equipe
        team_reqs = spec.get("team_requirements", [])[cite: 15]
        if isinstance(team_reqs, list):
            for req in team_reqs:
                if isinstance(req, dict):
                    skill = req.get("skill") or req.get("name")[cite: 15]
                    if skill:
                        skills.add(skill)[cite: 15]
        
        # 2. Competences des taches
        for node in dag:
            for skill in node.skills_required:
                skills.add(skill)[cite: 15]
        
        # 3. Competences implicites basees sur les types de taches
        for node in dag:
            implicit_skills = self._get_implicit_skills(node.task_type)[cite: 15]
            skills.update(implicit_skills)[cite: 15]
        
        # 4. Competences issues des integrations
        integrations = spec.get("integrations", [])[cite: 15]
        if isinstance(integrations, list):
            for integration in integrations:
                if isinstance(integration, dict):
                    integration_type = integration.get("type")[cite: 15]
                    if integration_type:
                        skills.add(f"integration_{integration_type}")[cite: 15]
        
        logger.debug(f"Extracted {len(skills)} required skills")[cite: 15]
        return skills[cite: 15]
    
    def _extract_task_skills(self, task_spec: Dict[str, Any]) -> List[str]:
        """
        Extrait les competences d'une tache specifique.
        
        Args:
            task_spec: Specification de la tache
            
        Returns:
            List[str]: Liste des competences requises
        """
        skills = task_spec.get("skills_required", []) or [][cite: 15]
        if not isinstance(skills, list):
            skills = [skills] if skills else []
        
        # Competences implicites basees sur le type
        task_type = task_spec.get("type", "").lower()[cite: 15]
        implicit = self._get_implicit_skills(task_type)[cite: 15]
        if implicit:
            skills.extend(implicit)[cite: 15]
        
        return list(set(skills))[cite: 15]
    
    def _get_implicit_skills(self, task_type: str) -> List[str]:
        """
        Retourne les competences implicites pour un type de tache.
        
        Args:
            task_type: Type de la tache
            
        Returns:
            List[str]: Competences implicites
        """
        mapping = {
            "contract_generation": ["solidity", "smart_contract", "openzeppelin"],[cite: 15]
            "test_generation": ["foundry", "forge_testing", "solidity"],[cite: 15]
            "security_audit": ["slither", "security_analysis", "formal_verification"],[cite: 15]
            "formal_verification": ["halmos", "symbolic_execution", "z3"],[cite: 15]
            "optimization": ["gas_optimization", "solidity"],[cite: 15]
            "deployment": ["foundry_script", "anvil", "deployment"],[cite: 15]
            "documentation": ["natspec", "technical_writing"],[cite: 15]
            "review": ["code_review", "solidity"],[cite: 15]
            "analysis": ["project_analysis", "requirements"],[cite: 15]
            "design": ["smart_contract_design", "solidity"],[cite: 15]
            "custom": [][cite: 15]
        }
        return mapping.get(task_type.lower(), [])[cite: 15]
    
    def _check_available_skills(self, required_skills: Set[str]) -> Set[str]:
        """
        Verifie quelles competences sont disponibles.
        
        Args:
            required_skills: Ensemble des competences requises
            
        Returns:
            Set[str]: Competences manquantes
        """
        missing = set()[cite: 15]
        
        for skill_id in required_skills:
            if not self.skill_registry.has_skill(skill_id):
                missing.add(skill_id)[cite: 15]
                logger.debug(f"Skill {skill_id} is missing")[cite: 15]
        
        return missing[cite: 15]
    
    async def _create_missing_skills(
        self,
        missing_skills: Set[str],
        spec: Dict[str, Any]
    ) -> Set[str]:
        """
        Cree dynamiquement les competences manquantes.
        
        Args:
            missing_skills: Competences manquantes
            spec: Specification du projet
            
        Returns:
            Set[str]: Competences toujours manquantes apres creation
        """
        still_missing = set()[cite: 15]
        
        for skill_id in missing_skills:
            try:
                # Tentative de creation via le LLM
                if self.llm_client:
                    skill_class = await self._synthesize_skill(skill_id, spec)[cite: 15]
                    if skill_class:
                        # Enregistrement dans le registre
                        metadata = SkillMetadata(
                            skill_id=skill_id,[cite: 15]
                            name=skill_id,[cite: 15]
                            description=f"Auto-generated skill: {skill_id}",[cite: 15]
                            version="1.0.0",[cite: 15]
                            scope=SkillScope.PROJECT,[cite: 15]
                            tags={"auto_generated", "architect_created"}[cite: 15]
                        )
                        self.skill_registry.register(skill_id, skill_class, metadata)[cite: 15]
                        logger.info(f"Auto-generated skill: {skill_id}")[cite: 15]
                        continue[cite: 15]
                    else:
                        logger.warning(f"Skill synthesis failed for {skill_id}, marking as missing")[cite: 15]
                else:
                    logger.warning(f"No LLM client available, cannot synthesize skill {skill_id}")[cite: 15]
                
                # Si pas de LLM ou echec, on garde comme manquante
                still_missing.add(skill_id)[cite: 15]
                
            except Exception as e:
                logger.error(f"Failed to create skill {skill_id}: {str(e)}")[cite: 15]
                still_missing.add(skill_id)[cite: 15]
        
        return still_missing[cite: 15]
    
    async def _synthesize_skill(
        self,
        skill_id: str,
        spec: Dict[str, Any]
    ) -> Optional[type]:
        """
        Synthetise une nouvelle competence via le LLM.
        
        Args:
            skill_id: ID de la competence a creer
            spec: Specification du projet
            
        Returns:
            Optional[type]: Classe de competence ou None
        """
        if not self.llm_client:
            logger.debug(f"No LLM client for skill synthesis: {skill_id}")[cite: 15]
            return None[cite: 15]
        
        try:
            # Construction du prompt pour la generation
            prompt = f"""
            Create a new skill class for the Smart Contract Dev Pipeline.
            
            Skill ID: {skill_id}
            Project: {spec.get('name', 'Unknown')}
            Description: {spec.get('description', 'No description')}
            
            The skill class should:
            1. Inherit from BaseSkill
            2. Have a proper execute() method
            3. Include system prompt rules
            
            Return only the Python class code.
            """[cite: 15]
            
            # Generation du code via LLM
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are an expert at generating Python code for smart contract development skills.",
                temperature=0.3
            )[cite: 15]
            
            logger.info(f"Skill generation response received for {skill_id}")[cite: 15]
            
            from src.agents.base.skill import BaseSkill[cite: 15]
            from pydantic import BaseModel[cite: 15]
            
            # Classe dynamique factice
            class DynamicSkill(BaseSkill):
                skill_id = skill_id[cite: 15]
                name = skill_id[cite: 15]
                description = f"Auto-generated skill: {skill_id}"[cite: 15]
                
                async def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
                    return {
                        "status": "SUCCESS",[cite: 15]
                        "result": f"Executed {skill_id} with params: {params}"[cite: 15]
                    }
                
                def get_system_prompt_rules(self) -> str:
                    return f"Execute the {skill_id} skill."[cite: 15]
            
            return DynamicSkill[cite: 15]
            
        except Exception as e:
            logger.error(f"Skill synthesis failed for {skill_id}: {str(e)}")[cite: 15]
            return None[cite: 15]
    
    # =========================================================================
    # ANALYSE ET RAPPORTS
    # =========================================================================
    
    def get_analysis(self, project_id: str) -> Optional[ProjectAnalysis]:
        """
        Recupere l'analyse d'un projet.
        
        Args:
            project_id: ID du projet
            
        Returns:
            Optional[ProjectAnalysis]: Analyse du projet ou None
        """
        for analysis in self._analysis_history:
            if analysis.project_id == project_id:
                return analysis[cite: 15]
        return None[cite: 15]
    
    def get_recent_analyses(self, limit: int = 10) -> List[ProjectAnalysis]:
        """
        Recupere les analyses recentes.
        
        Args:
            limit: Nombre maximum d'analyses
            
        Returns:
            List[ProjectAnalysis]: Analyses recentes
        """
        return sorted(
            self._analysis_history,
            key=lambda x: x.created_at,[cite: 15]
            reverse=True
        )[:limit][cite: 15]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.
        
        Returns:
            Dict: Statistiques detaillees
        """
        total_analyses = len(self._analysis_history)[cite: 15]
        total_tasks = sum(a.total_tasks for a in self._analysis_history)[cite: 15]
        total_skills = sum(len(a.skills_required) for a in self._analysis_history)[cite: 15]
        
        return {
            "total_analyses": total_analyses,[cite: 15]
            "total_tasks": total_tasks,[cite: 15]
            "total_skills_required": total_skills,[cite: 15]
            "average_complexity": (
                sum(a.complexity_score for a in self._analysis_history) / total_analyses
                if total_analyses > 0 else 0
            ),[cite: 15]
            "average_tasks": total_tasks / total_analyses if total_analyses > 0 else 0,[cite: 15]
            "analysis_history": [a.to_dict() for a in self._analysis_history[-5:]],[cite: 15]
            **super().health_check()
        }
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<ArchitectAgent(agent_id='{self.agent_id}', analyses={len(self._analysis_history)})>"[cite: 15]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convertit l'agent en dictionnaire.
        
        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,[cite: 15]
            "name": self.name,[cite: 15]
            "type": "ArchitectAgent",[cite: 15]
            "analyses_count": len(self._analysis_history),[cite: 15]
            "skills_count": len(self.skills),[cite: 15]
            "health": self.health_check()[cite: 15]
        }