# src/security/formal_verifier.py
import asyncio
from typing import Dict, Any, Optional
from src.core.exceptions import ValidationError

class HalmosVerifier:
    """Vérificateur formel basé sur Halmos."""
    
    def __init__(self, project_path: str = "."):
        self.project_path = project_path

    async def verify_invariants(self, check_function: Optional[str] = None) -> Dict[str, Any]:
        """Exécute la vérification formelle des invariants."""
        cmd = ["halmos"]
        if check_function:
            cmd.extend(["--match-test", check_function])
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        output = stdout.decode()
        error = stderr.decode()
        
        return {
            "success": proc.returncode == 0,
            "output": output,
            "error": error,
            "counterexample": self.parse_counterexample(output)
        }

    def parse_counterexample(self, halmos_output: str) -> Dict[str, Any]:
        """Extrait le contre-exemple mathématique de la sortie Halmos."""
        return {
            "found": "Violated" in halmos_output,
            "details": halmos_output if "Violated" in halmos_output else None
        }