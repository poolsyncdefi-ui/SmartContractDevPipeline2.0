# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Dockerfile
# ==============================================================================
# Fichier: Dockerfile
# Description: Image Docker pour le pipeline.
# ==============================================================================

FROM python:3.11-slim

WORKDIR /app

# Installer les dépendances système
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Installer Foundry
RUN curl -L https://foundry.paradigm.xyz | bash && \
    /root/.foundry/bin/foundryup

# Copier les dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Créer le workspace
RUN mkdir -p /app/workspace /app/contracts

# Exposer le port de l'API
EXPOSE 8000

# Commande par défaut
CMD ["uvicorn", "src.api.web_dashboard:app", "--host", "0.0.0.0", "--port", "8000"]