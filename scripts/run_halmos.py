import subprocess
import sys

def run_halmos():
    print("[*] Lancement de la vérification formelle Halmos...")
    
    # Commande épurée pour Halmos
    cmd = [
        "halmos",
        "--contract",
        "CounterTest"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("[+] Vérification formelle Halmos terminée avec succès.")
    except subprocess.CalledProcessError as e:
        print("[-] Halmos a détecté une violation de propriété ou une erreur.", file=sys.stderr)
        sys.exit(e.returncode)

if __name__ == "__main__":
    run_halmos()