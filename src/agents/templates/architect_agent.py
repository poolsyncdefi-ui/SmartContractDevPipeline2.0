# src/agents/templates/architect_agent.py
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List
import yaml

class ArchitectAgent(AbstractAgent):
    """Agent spécialisé dans l'architecture et l'orchestration."""
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse la spécification et génère le DAG."""
        yaml_content = task_data.get("yaml_content", "")
        spec = self.parse_yaml_spec(yaml_content)
        dag = self.generate_dag_nodes(spec)
        
        return {
            "status": "success",
            "spec": spec,
            "dag": dag,
            "skills_required": self._extract_skills(spec)
        }

    def parse_yaml_spec(self, yaml_text: str) -> Dict[str, Any]:
        """Parse la spécification YAML."""
        return yaml.safe_load(yaml_text) or {}

    def generate_dag_nodes(self, parsed_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Génère les nœuds du DAG."""
        return parsed_spec.get("sprint_workflow", [])

    def _extract_skills(self, spec: Dict[str, Any]) -> List[str]:
        """Extrait la liste des compétences requises."""
        requirements = spec.get("team_requirements", [])
        return [req.get("skill") for req in requirements if req.get("skill")]