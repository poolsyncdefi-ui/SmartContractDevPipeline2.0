# 🛡️ Smart Contract Dev Pipeline 2.0

Pipeline robuste pour le développement, le test, l'analyse statique et la vérification formelle de Smart Contracts.

## 🚀 Fonctionnalités
- **Compilation** : Foundry (Forge)
- **Tests** : Foundry (Unitaires et Fuzzing)
- **Analyse Statique** : Slither
- **Vérification Formelle** : Halmos
- **Infrastructure** : Docker (Anvil Node & API Dashboard)
- **API** : FastAPI pour orchestrer les tests

## 🛠️ Prérequis
- Docker & Docker Compose
- Python 3.11+
- Foundry (`foundryup`)

## 📦 Installation
```bash
pip install -r requirements.txt
forge install