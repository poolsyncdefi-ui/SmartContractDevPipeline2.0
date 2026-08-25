# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Global Pipeline Orchestrator
# ==============================================================================

import subprocess
import sys
import os

def run_command(command, description):
    print(f"\n[PIPELINE] 🚀 {description}...")
    try:
        result = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True
        )
        print(f"[PIPELINE] ✅ {description} réussi.")
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[PIPELINE] ❌ Erreur lors de : {description}")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        return False

def main():
    print("==================================================")
    print(" Smart Contract Dev Pipeline 2.0 - Exécution globale")
    print("==================================================")

    # 1. Analyse Statique avec Slither
    if not run_command(["python", "scripts/run_slither.py"], "Analyse statique Slither"):
        print("[PIPELINE] ⚠️ L'analyse Slither a détecté des alertes ou une erreur.")

    # 2. Tests unitaires et Fuzzing avec Foundry (Forge)
    if not run_command(["forge", "test"], "Tests unitaires Foundry"):
        print("[PIPELINE] ❌ Échec des tests Forge.")
        sys.exit(1)

    # 3. Vérification Formelle avec Halmos
    if not run_command(["python", "scripts/run_halmos.py"], "Vérification formelle Halmos"):
        print("[PIPELINE] ❌ Échec de la vérification formelle Halmos.")
        sys.exit(1)

    print("\n==================================================")
    print(" ✅ Pipeline exécuté avec succès de bout en bout !")
    print("==================================================")

if __name__ == "__main__":
    main()