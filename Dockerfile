# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Dockerfile
# ==============================================================================

FROM python:3.11-slim

# 1. Installation des dépendances système essentielles
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. Définition du répertoire de travail
WORKDIR /app

# 3. Installation de Foundry (Forge, Cast, Anvil, Chisel)
RUN curl -L https://foundry.paradigm.xyz | bash
ENV PATH="/root/.foundry/bin:${PATH}"
RUN foundryup

# 4. Copie des dépendances Python et installation
COPY requirements.txt* .
RUN pip install --no-cache-dir --upgrade pip
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

# Installation explicite des outils principaux du pipeline si non présents dans requirements
RUN pip install --no-cache-dir slither-analyzer halmos fastapi uvicorn web3

# 5. Copie du code source du projet
COPY . .

# 6. Exposition du port pour l'API Dashboard
EXPOSE 8000

# 7. Commande par défaut
CMD ["uvicorn", "src.api.web_dashboard:app", "--host", "0.0.0.0", "--port", "8000"]