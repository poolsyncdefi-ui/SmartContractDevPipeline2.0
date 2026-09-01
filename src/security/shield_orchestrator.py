# src/security/shield_orchestrator.py
from typing import Dict, Any
from src.security.threat_simulator import ThreatSimulator
from src.security.fuzzing.foundry_runner import FoundryWrapper
from src.security.static.slither_analyzer import SlitherWrapper
from src.security.formal_verifier import HalmosVerifier
from src.config.settings import settings

class SecurityShield:
    """Orchestrateur global du bouclier de sécurité."""
    
    def __init__(self, project_path: str = "."):
        self.project_path = project_path
        self.slither = SlitherWrapper(project_path)
        self.foundry = FoundryWrapper(project_path)
        self.simulator = ThreatSimulator(project_path)
        self.halmos = HalmosVerifier(project_path)

    async def run_full_audit(self, contract_address: str = None) -> Dict[str, Any]:
        """Exécute l'audit complet en 4 niveaux."""
        results = {}
        
        # Niveau 1 : Slither (statique)
        slither_result = await self.slither.analyze()
        results["slither"] = slither_result
        
        # Niveau 2 : Foundry (fuzzing)
        foundry_result = await self.foundry.compile_and_test()
        results["foundry"] = foundry_result
        
        # Niveau 3 : Threat Simulator (anvil)
        if contract_address:
            flash_loan = await self.simulator.simulate_flash_loan_attack(contract_address)
            oracle = await self.simulator.simulate_oracle_manipulation(contract_address)
            results["threat"] = {"flash_loan": flash_loan, "oracle": oracle}
        
        # Niveau 4 : Halmos (formel)
        halmos_result = await self.halmos.verify_invariants()
        results["halmos"] = halmos_result
        
        # Sécurité globale
        results["secure"] = all([
            slither_result.get("success", False),
            foundry_result.get("success", False),
            halmos_result.get("success", False)
        ])
        
        return results