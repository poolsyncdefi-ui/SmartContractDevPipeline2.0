# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - FastAPI Dashboard & Orchestrator
# ==============================================================================

from fastapi import FastAPI, HTTPException
import subprocess
import os

app = FastAPI(
    title="Smart Contract Dev Pipeline 2.0 API",
    description="API de pilotage et de reporting pour les smart contracts (Foundry, Slither, Halmos)",
    version="2.0.0"
)

@app.get("/")
def read_root():
    return {
        "status": "online",
        "pipeline": "Smart Contract Dev Pipeline 2.0",
        "modules": {
            "halmos": "/run/halmos",
            "slither": "/run/slither",
            "status": "/status"
        }
    }

@app.get("/status")
def get_pipeline_status():
    return {
        "solc_version": "0.8.33",
        "foundry_version": "1.7.1",
        "pipeline_status": "ready"
    }

@app.post("/run/halmos")
def trigger_halmos():
    """Exécute la vérification formelle Halmos via le script Python dédié."""
    script_path = os.path.join("scripts", "run_halmos.py")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Script run_halmos.py introuvable.")
    
    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "success": True,
            "message": "Vérification formelle Halmos exécutée avec succès.",
            "output": result.stdout
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "message": "Erreur lors de l'exécution d'Halmos.",
            "error": e.stderr
        }

@app.post("/run/slither")
def trigger_slither():
    """Exécute l'analyse statique Slither via le script Python dédié."""
    script_path = os.path.join("scripts", "run_slither.py")
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Script run_slither.py introuvable.")
    
    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            check=True
        )
        return {
            "success": True,
            "message": "Analyse statique Slither exécutée avec succès.",
            "output": result.stdout
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "message": "Erreur lors de l'exécution de Slither.",
            "error": e.stderr
        }