# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Deployment Script (Web3.py)
# ==============================================================================

import os
import json
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

def main():
    print("[DEPLOY] 🚀 Initialisation du déploiement...")

    # Configuration du fournisseur RPC (par défaut Anvil local)
    rpc_url = os.getenv("ETH_RPC_URL", "http://127.0.0.1:8545")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        print(f"[DEPLOY] ❌ Impossible de se connecter au nœud RPC : {rpc_url}")
        return

    print(f"[DEPLOY] ✅ Connecté au réseau Ethereum (Chain ID: {w3.eth.chain_id})")

    # Compte de déploiement (compte par défaut Anvil #0)
    # En production, utilisez une clé privée sécurisée via .env
    account = w3.eth.accounts[0]
    w3.eth.default_account = account
    print(f"[DEPLOY] 👤 Utilisation du compte : {account}")

    # Chemin vers les artefacts de compilation Foundry (forge build génère out/)
    # Exemple pour Counter.sol : out/Counter.sol/Counter.json
    artifact_path = os.path.join("out", "Counter.sol", "Counter.json")
    
    if not os.path.exists(artifact_path):
        print(f"[DEPLOY] ❌ Artefact introuvable : {artifact_path}. Veuillez exécuter 'forge build' au préalable.")
        return

    with open(artifact_path, "r") as f:
        artifact = json.load(f)
        abi = artifact["abi"]
        bytecode = artifact["bytecode"]["object"]

    # Création du contrat et déploiement
    print("[DEPLOY] 📦 Déploiement du contrat Counter...")
    CounterContract = w3.eth.contract(abi=abi, bytecode=bytecode)
    
    # Construction et envoi de la transaction de déploiement
    tx_hash = CounterContract.constructor().transact()
    tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    print(f"[DEPLOY] ✅ Contrat déployé avec succès !")
    print(f"[DEPLOY] 📍 Adresse du contrat : {tx_receipt.contractAddress}")
    print(f"[DEPLOY] ⛽ Gas utilisé : {tx_receipt.gasUsed}")

if __name__ == "__main__":
    main()