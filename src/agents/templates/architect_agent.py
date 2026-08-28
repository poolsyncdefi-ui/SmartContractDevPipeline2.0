# src/agents/templates/architect_agent.py
from typing import Dict, Any, List
import yaml
from src.agents.base.abstract_agent import AbstractAgent

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
            "dag": dag
        }
    
    def parse_yaml_spec(self, yaml_text: str) -> Dict[str, Any]:
        """Parse la spécification YAML."""
        return yaml.safe_load(yaml_text) or {}
    
    def generate_dag_nodes(self, parsed_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Génère les nœuds du DAG."""
        return parsed_spec.get("tasks", [])