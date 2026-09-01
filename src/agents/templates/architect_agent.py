# src/agents/templates/architect_agent.py

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
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List, Optional, Set, Tuple
from datetime import datetime
import yaml
import json
import logging
import re
from enum import Enum
from dataclasses import dataclass, field

# Import des modules du pipeline
from src.core.exceptions import PipelineError, LLMError, SkillNotFoundError
from src.core.models import ProjectConfig, Skill
from src.agents.factory.skill_registry import SkillRegistry, SkillMetadata, SkillScope
from src.persistence.knowledge_base import KnowledgeBase

# Configuration du logging
logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    """
    Types de taches possibles dans le DAG.
    """
    ANALYSIS = "analysis"
    DESIGN = "design"
    CONTRACT_GENERATION = "contract_generation"
    TEST_GENERATION = "test_generation"
    SECURITY_AUDIT = "security_audit"
    FORMAL_VERIFICATION = "formal_verification"
    OPTIMIZATION = "optimization"
    DEPLOYMENT = "deployment"
    DOCUMENTATION = "documentation"
    REVIEW = "review"
    CUSTOM = "custom"


class TaskStatus(str, Enum):
    """
    Statuts possibles pour une tache dans le DAG.
    """
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


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
    task_id: str
    name: str
    task_type: TaskType
    description: str = ""
    skills_required: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 5
    estimated_duration: float = 0.0
    assigned_agent: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit le nœud en dictionnaire."""
        return {
            "task_id": self.task_id,
            "name": self.name,
            "task_type": self.task_type.value,
            "description": self.description,
            "skills_required": self.skills_required,
            "dependencies": self.dependencies,
            "parameters": self.parameters,
            "status": self.status.value,
            "priority": self.priority,
            "estimated_duration": self.estimated_duration,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "metadata": self.metadata
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
    project_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    chain: str = "ethereum"
    complexity_score: int = 1
    total_tasks: int = 0
    tasks: List[TaskNode] = field(default_factory=list)
    skills_required: Set[str] = field(default_factory=set)
    missing_skills: Set[str] = field(default_factory=set)
    estimated_duration: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convertit l'analyse en dictionnaire."""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "chain": self.chain,
            "complexity_score": self.complexity_score,
            "total_tasks": self.total_tasks,
            "tasks": [t.to_dict() for t in self.tasks],
            "skills_required": list(self.skills_required),
            "missing_skills": list(self.missing_skills),
            "estimated_duration": self.estimated_duration,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata
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
        super().__init__(agent_id=agent_id, name=name, skills=skills, llm_client=llm_client)
        self.knowledge_base = knowledge_base
        self.skill_registry = skill_registry or SkillRegistry()
        self.max_tasks = max_tasks
        self.auto_create_skills = auto_create_skills
        self._analysis_history: List[ProjectAnalysis] = []
        
        logger.info(f"ArchitectAgent initialized: {agent_id}")
    
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
        start_time = datetime.utcnow()
        
        try:
            # 1. Extraction des donnees
            yaml_content = task_data.get("yaml_content", "")
            project_id = task_data.get("project_id", f"proj_{datetime.utcnow().timestamp()}")
            project_name = task_data.get("project_name", "Unnamed Project")
            
            if not yaml_content:
                raise ValueError("No yaml_content provided")
            
            # 2. Parsing de la specification YAML
            spec = self.parse_yaml_spec(yaml_content)
            if not spec:
                raise ValueError("Invalid or empty YAML specification")
            
            # 3. Validation de la specification
            self._validate_spec(spec)
            
            # 4. Analyse de la complexite
            complexity = self._analyze_complexity(spec)
            
            # 5. Generation du DAG
            dag = await self.generate_dag(spec, project_id)
            
            # 6. Extraction des competences requises
            skills_required = self._extract_skills(spec, dag)
            
            # 7. Verification des competences disponibles
            missing_skills = self._check_available_skills(skills_required)
            
            # 8. Creation dynamique des competences manquantes
            if missing_skills and self.auto_create_skills:
                missing_skills = await self._create_missing_skills(missing_skills, spec)
            
            # 9. Construction de l'analyse
            analysis = ProjectAnalysis(
                project_id=project_id,
                name=project_name,
                description=spec.get("description", ""),
                version=spec.get("version", "1.0.0"),
                chain=spec.get("chain", "ethereum"),
                complexity_score=complexity,
                total_tasks=len(dag),
                tasks=dag,
                skills_required=skills_required,
                missing_skills=missing_skills,
                estimated_duration=sum(t.estimated_duration for t in dag),
                metadata={
                    "analysis_time": (datetime.utcnow() - start_time).total_seconds(),
                    "yaml_size": len(yaml_content),
                    "auto_created_skills": len(skills_required) - len(missing_skills)
                }
            )
            
            # 10. Persistance de l'analyse
            self._analysis_history.append(analysis)
            
            # 11. Logging de l'execution
            await self.log_execution(
                task_id=task_data.get("task_id", "unknown"),
                prompt=yaml_content[:500],  # Log partiel
                response=f"Generated {len(dag)} tasks",
                tool_output=json.dumps(analysis.to_dict(), indent=2)[:500]
            )
            
            logger.info(f"Architect analysis complete: {len(dag)} tasks, {len(skills_required)} skills required")
            
            return {
                "status": "SUCCESS",
                "analysis": analysis.to_dict(),
                "dag": [t.to_dict() for t in dag],
                "skills_required": list(skills_required),
                "missing_skills": list(missing_skills),
                "complexity_score": complexity,
                "estimated_duration": analysis.estimated_duration,
                "metadata": {
                    "execution_time": (datetime.utcnow() - start_time).total_seconds()
                }
            }
            
        except Exception as e:
            logger.error(f"ArchitectAgent execution failed: {str(e)}")
            return {
                "status": "FAILED",
                "error": str(e),
                "execution_time": (datetime.utcnow() - start_time).total_seconds()
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
            spec = yaml.safe_load(yaml_text)
            if not spec:
                logger.warning("Empty YAML specification")
                return {}
            return spec
        except yaml.YAMLError as e:
            logger.error(f"YAML parsing error: {str(e)}")
            raise ValueError(f"Invalid YAML: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error parsing YAML: {str(e)}")
            raise
    
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
            raise ValueError("Project 'name' is required")
        
        # Verification de la structure des taches
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or spec.get("workflow")
        if not tasks:
            raise ValueError("No tasks or workflow defined in specification")
        
        if not isinstance(tasks, list):
            raise ValueError("Tasks must be a list")
        
        if len(tasks) > self.max_tasks:
            raise ValueError(f"Too many tasks ({len(tasks)} > {self.max_tasks})")
        
        # Validation des taches individuelles
        for i, task in enumerate(tasks):
            if "id" not in task and "name" not in task:
                raise ValueError(f"Task {i} missing 'id' or 'name'")
            if "type" not in task:
                raise ValueError(f"Task {i} missing 'type'")
        
        logger.debug(f"Spec validation passed: {len(tasks)} tasks")
    
    def _analyze_complexity(self, spec: Dict[str, Any]) -> int:
        """
        Analyse la complexite du projet.
        
        Args:
            spec: Specification du projet
            
        Returns:
            int: Score de complexite (1-10)
        """
        score = 1
        
        # Facteurs de complexite
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or []
        num_tasks = len(tasks)
        
        # Nombre de taches
        if num_tasks > 20:
            score += 3
        elif num_tasks > 10:
            score += 2
        elif num_tasks > 5:
            score += 1
        
        # Types de taches
        task_types = [t.get("type", "").lower() for t in tasks]
        if "security_audit" in task_types or "formal_verification" in task_types:
            score += 2
        if "deployment" in task_types:
            score += 1
        
        # Integrations
        integrations = spec.get("integrations", [])
        if integrations:
            score += len(integrations)
        
        # Dependances
        has_dependencies = any(t.get("dependencies") for t in tasks)
        if has_dependencies:
            score += 1
        
        return min(10, max(1, score))
    
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
        tasks = spec.get("tasks") or spec.get("sprint_workflow") or spec.get("workflow", [])
        dag = []
        task_map = {}
        
        # Construction des nœuds
        for i, task_spec in enumerate(tasks):
            task_id = task_spec.get("id") or task_spec.get("name", f"task_{i}")
            
            # Determination du type
            task_type_str = task_spec.get("type", "custom").lower()
            try:
                task_type = TaskType(task_type_str)
            except ValueError:
                task_type = TaskType.CUSTOM
                logger.warning(f"Unknown task type '{task_type_str}' for {task_id}, using CUSTOM")
            
            # Extraction des competences requises
            skills = self._extract_task_skills(task_spec)
            
            # Extraction des dependances
            deps = task_spec.get("dependencies", [])
            
            # Creation du nœud
            node = TaskNode(
                task_id=task_id,
                name=task_spec.get("name", task_id),
                task_type=task_type,
                description=task_spec.get("description", ""),
                skills_required=skills,
                dependencies=deps,
                parameters=task_spec.get("parameters", {}),
                priority=task_spec.get("priority", 5),
                estimated_duration=task_spec.get("estimated_duration", 0.0),
                metadata={
                    "source": task_spec,
                    "index": i
                }
            )
            
            dag.append(node)
            task_map[task_id] = node
        
        # Validation des dependances (cycles)
        self._validate_dag(dag)
        
        # Tri topologique des taches
        sorted_dag = self._topological_sort(dag)
        
        # Enrichissement avec le contexte RAG
        if self.knowledge_base:
            enriched_dag = await self._enrich_with_context(sorted_dag, spec)
            return enriched_dag
        
        return sorted_dag
    
    def _validate_dag(self, dag: List[TaskNode]) -> None:
        """
        Valide le DAG pour eviter les cycles.
        
        Args:
            dag: Liste des nœuds de taches
            
        Raises:
            ValueError: Si un cycle est detecte
        """
        # Construction du graphe
        graph = {node.task_id: node.dependencies for node in dag}
        
        # Detection des cycles avec DFS
        visited = set()
        rec_stack = set()
        
        def has_cycle(node_id: str) -> bool:
            visited.add(node_id)
            rec_stack.add(node_id)
            
            for dep in graph.get(node_id, []):
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True
            
            rec_stack.remove(node_id)
            return False
        
        for node_id in graph:
            if node_id not in visited:
                if has_cycle(node_id):
                    raise ValueError(f"Cycle detected in DAG involving node {node_id}")
        
        # Verification des dependances existantes
        all_task_ids = {node.task_id for node in dag}
        for node in dag:
            for dep in node.dependencies:
                if dep not in all_task_ids:
                    raise ValueError(f"Task {node.task_id} depends on {dep} which does not exist")
        
        logger.debug(f"DAG validation passed: {len(dag)} tasks, no cycles")
    
    def _topological_sort(self, dag: List[TaskNode]) -> List[TaskNode]:
        """
        Tri topologique des taches (Kahn's algorithm).
        
        Args:
            dag: Liste des nœuds de taches
            
        Returns:
            List[TaskNode]: Taches triees topologiquement
        """
        from collections import deque
        
        # Construction du graphe
        task_map = {node.task_id: node for node in dag}
        in_degree = {node.task_id: 0 for node in dag}
        graph = {node.task_id: [] for node in dag}
        
        for node in dag:
            for dep in node.dependencies:
                if dep in task_map:
                    graph[dep].append(node.task_id)
                    in_degree[node.task_id] += 1
        
        # File des taches sans dependances
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        sorted_tasks = []
        
        while queue:
            tid = queue.popleft()
            sorted_tasks.append(task_map[tid])
            
            for next_tid in graph.get(tid, []):
                in_degree[next_tid] -= 1
                if in_degree[next_tid] == 0:
                    queue.append(next_tid)
        
        # Verification: tous les nœuds sont-ils inclus?
        if len(sorted_tasks) != len(dag):
            logger.warning("Topological sort incomplete - possible cycle or missing nodes")
            # Retourner l'ordre original en cas de probleme
            return dag
        
        return sorted_tasks
    
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
            return dag
        
        try:
            # Construction de la requete
            query = f"Smart contract development: {spec.get('name', '')} {spec.get('description', '')}"
            context_docs = self.knowledge_base.query_context(query, n_results=3)
            
            if context_docs:
                # Enrichissement des taches avec le contexte
                for node in dag:
                    if not hasattr(node, 'metadata'):
                        node.metadata = {}
                    node.metadata['rag_context'] = context_docs
                    
                    # Amelioration des descriptions avec le contexte
                    if context_docs and len(context_docs) > 0:
                        node.description += f"\n\nContext: {context_docs[0][:200]}..."
                
                logger.info(f"DAG enriched with {len(context_docs)} RAG documents")
        
        except Exception as e:
            logger.warning(f"RAG enrichment failed: {str(e)}")
        
        return dag
    
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
        skills = set()
        
        # 1. Competences explicites dans les requirements de l'equipe
        team_reqs = spec.get("team_requirements", [])
        for req in team_reqs:
            skill = req.get("skill")
            if skill:
                skills.add(skill)
        
        # 2. Competences des taches
        for node in dag:
            for skill in node.skills_required:
                skills.add(skill)
        
        # 3. Competences implicites basees sur les types de taches
        for node in dag:
            implicit_skills = self._get_implicit_skills(node.task_type)
            skills.update(implicit_skills)
        
        # 4. Competences issues des integrations
        integrations = spec.get("integrations", [])
        for integration in integrations:
            if integration.get("type"):
                skills.add(f"integration_{integration['type']}")
        
        logger.debug(f"Extracted {len(skills)} required skills")
        return skills
    
    def _extract_task_skills(self, task_spec: Dict[str, Any]) -> List[str]:
        """
        Extrait les competences d'une tache specifique.
        
        Args:
            task_spec: Specification de la tache
            
        Returns:
            List[str]: Liste des competences requises
        """
        skills = task_spec.get("skills_required", [])
        
        # Competences implicites basees sur le type
        task_type = task_spec.get("type", "").lower()
        implicit = self._get_implicit_skills(task_type)
        if implicit:
            skills.extend(implicit)
        
        return list(set(skills))
    
    def _get_implicit_skills(self, task_type: str) -> List[str]:
        """
        Retourne les competences implicites pour un type de tache.
        
        Args:
            task_type: Type de la tache
            
        Returns:
            List[str]: Competences implicites
        """
        mapping = {
            "contract_generation": ["solidity", "smart_contract", "openzeppelin"],
            "test_generation": ["foundry", "forge_testing", "solidity"],
            "security_audit": ["slither", "security_analysis", "formal_verification"],
            "formal_verification": ["halmos", "symbolic_execution", "z3"],
            "optimization": ["gas_optimization", "solidity"],
            "deployment": ["foundry_script", "anvil", "deployment"],
            "documentation": ["natspec", "technical_writing"],
            "review": ["code_review", "solidity"],
            "analysis": ["project_analysis", "requirements"],
            "design": ["smart_contract_design", "solidity"],
            "custom": []
        }
        return mapping.get(task_type.lower(), [])
    
    def _check_available_skills(self, required_skills: Set[str]) -> Set[str]:
        """
        Verifie quelles competences sont disponibles.
        
        Args:
            required_skills: Ensemble des competences requises
            
        Returns:
            Set[str]: Competences manquantes
        """
        missing = set()
        
        for skill_id in required_skills:
            if not self.skill_registry.has_skill(skill_id):
                missing.add(skill_id)
                logger.debug(f"Skill {skill_id} is missing")
        
        return missing
    
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
        still_missing = set()
        
        for skill_id in missing_skills:
            try:
                # Tentative de creation via le LLM
                if self.llm_client:
                    skill = await self._synthesize_skill(skill_id, spec)
                    if skill:
                        # Enregistrement dans le registre
                        metadata = SkillMetadata(
                            skill_id=skill_id,
                            name=skill_id,
                            description=f"Auto-generated skill: {skill_id}",
                            version="1.0.0",
                            scope=SkillScope.PROJECT,
                            tags={"auto_generated", "architect_created"}
                        )
                        self.skill_registry.register(skill_id, skill, metadata)
                        logger.info(f"Auto-generated skill: {skill_id}")
                        continue
                
                # Si pas de LLM ou echec, on garde comme manquante
                still_missing.add(skill_id)
                logger.warning(f"Could not auto-generate skill: {skill_id}")
                
            except Exception as e:
                logger.error(f"Failed to create skill {skill_id}: {str(e)}")
                still_missing.add(skill_id)
        
        return still_missing
    
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
            return None
        
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
            """
            
            # Generation du code via LLM
            response = await self.llm_client.generate(
                prompt=prompt,
                system_prompt="You are an expert at generating Python code for smart contract development skills.",
                temperature=0.3
            )
            
            # Parsing et validation du code genere
            # Note: Dans la pratique, il faudrait executer le code genere
            # avec des precautions de securite (sandbox)
            logger.info(f"Skill generation response received for {skill_id}")
            
            # Pour l'instant, retourne une classe factice
            # Dans la vraie implementation, on extrairait la classe du code genere
            return None
            
        except Exception as e:
            logger.error(f"Skill synthesis failed: {str(e)}")
            return None
    
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
                return analysis
        return None
    
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
            key=lambda x: x.created_at,
            reverse=True
        )[:limit]
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Retourne les statistiques de l'agent.
        
        Returns:
            Dict: Statistiques detaillees
        """
        total_analyses = len(self._analysis_history)
        total_tasks = sum(a.total_tasks for a in self._analysis_history)
        total_skills = sum(len(a.skills_required) for a in self._analysis_history)
        
        return {
            "total_analyses": total_analyses,
            "total_tasks": total_tasks,
            "total_skills_required": total_skills,
            "average_complexity": sum(a.complexity_score for a in self._analysis_history) / total_analyses if total_analyses > 0 else 0,
            "average_tasks": total_tasks / total_analyses if total_analyses > 0 else 0,
            "analysis_history": [a.to_dict() for a in self._analysis_history[-5:]],
            **super().health_check()
        }
    
    # =========================================================================
    # REPRESENTATION
    # =========================================================================
    
    def __repr__(self) -> str:
        return f"<ArchitectAgent(agent_id='{self.agent_id}', analyses={len(self._analysis_history)})>"
    
    def to_dict(self) -> Dict:
        """
        Convertit l'agent en dictionnaire.
        
        Returns:
            Dict: Representation de l'agent
        """
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "type": "ArchitectAgent",
            "analyses_count": len(self._analysis_history),
            "skills_count": len(self.skills),
            "health": self.health_check()
        }