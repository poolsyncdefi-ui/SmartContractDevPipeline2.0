import subprocess
import sys

def run_slither():
    print("[*] Lancement de l'analyse statique Slither sur les contrats...")
    
    # Commande équivalente à celle testée dans le terminal
    cmd = [
        "slither", 
        "contracts/Counter.sol", 
        "--config-file", 
        "slither.config.json"
    ]
    
    try:
        result = subprocess.run(cmd, check=True)
        print("[+] Analyse Slither terminée avec succès.")
    except subprocess.CalledProcessError as e:
        print("[-] Slither a détecté des vulnérabilités ou une erreur d'exécution.", file=sys.stderr)
        sys.exit(e.returncode)

if __name__ == "__main__":
    run_slither()