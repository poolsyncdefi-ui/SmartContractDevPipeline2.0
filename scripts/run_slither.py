# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Slither Execution Script
# ==============================================================================

import subprocess
import sys
import os

def main():
    print("[SLITHER] Lancement de l'analyse statique...")
    
    config_path = "slither.config.json"
    output_json = "slither-report.json"
    
    # Commande Slither pointant sur le dossier courant avec le fichier de config
    cmd = ["slither", ".", "--config-file", config_path, "--json", output_json]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("[SLITHER] Analyse terminee avec succes.")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("[SLITHER] Slither a termine avec des alertes ou un code de retour specifique.")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        # Note : Slither renvoie souvent un code non nul s'il detecte des warnings/vulnerabilites.
        # Vous pouvez decider d'ajuster si cela doit bloquer ou non le pipeline.

if __name__ == "__main__":
    main()