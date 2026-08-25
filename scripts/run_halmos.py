# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Halmos Execution Script
# ==============================================================================

import subprocess
import sys
import os

def main():
    print("[HALMOS] Lancement de la verification formelle...")
    
    # Commande Halmos standard pour executer les tests symboliques
    cmd = ["halmos"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("[HALMOS] Verification formelle reussie avec succes.")
        if result.stdout:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("[HALMOS] Echec ou contre-exemple trouve par Halmos.")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()