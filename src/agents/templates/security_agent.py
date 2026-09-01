# src/agents/templates/security_agent.py
from src.agents.base.abstract_agent import AbstractAgent
from typing import Dict, Any, List

class SecurityAgent(AbstractAgent):
    """Agent spécialisé dans l'audit de sécurité."""
    
    async def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyse le code et détecte les vulnérabilités."""
        code = task_data.get("code", "")
        slither_report = task_data.get("slither_report", {})
        
        if slither_report:
            vulns = self.parse_slither_json(slither_report)
        else:
            vulns = await self.run_analysis(code)
        
        guide = self.format_remediation_guide(vulns)
        
        return {
            "status": "success",
            "vulnerabilities": vulns,
            "guide": guide,
            "secure": len(vulns) == 0
        }

    def parse_slither_json(self, raw_json: dict) -> List[Dict[str, Any]]:
        """Extrait les vulnérabilités du rapport Slither."""
        detectors = raw_json.get("results", {}).get("detectors", [])
        return [d for d in detectors if d.get("impact") in ["High", "Medium"]]

    async def run_analysis(self, code: str) -> List[Dict[str, Any]]:
        """Analyse le code et retourne les vulnérabilités."""
        # À implémenter avec les compétences
        return []

    def format_remediation_guide(self, vulnerabilities: List[Dict[str, Any]]) -> str:
        """Génère un guide de correction."""
        if not vulnerabilities:
            return "Aucune vulnérabilité détectée."
        guide = f"Detected {len(vulnerabilities)} vulnerabilities:\n"
        for v in vulnerabilities:
            guide += f"- {v.get('check', 'Unknown')}: {v.get('impact', '')}\n"
        return guide