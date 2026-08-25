# ==============================================================================
# start_pipeline.ps1 - Smart Contract Dev Pipeline 2.0
# Version avec gestion d'erreurs renforcée
# ==============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Smart Contract Dev Pipeline 2.0 - Demarrage" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 1. VERIFICATION DE L'ENVIRONNEMENT
# ============================================================================

Write-Host "[1] Verification de l'environnement..." -ForegroundColor Yellow

# Python
$pythonVersion = python --version 2>$null
if ($pythonVersion) {
    Write-Host "  Python : $pythonVersion" -ForegroundColor Green
} else {
    Write-Host "  Python : NON TROUVE" -ForegroundColor Red
    exit 1
}

# Docker
$dockerVersion = docker --version 2>$null
if ($dockerVersion) {
    Write-Host "  Docker : $dockerVersion" -ForegroundColor Green
} else {
    Write-Host "  Docker : NON TROUVE" -ForegroundColor Red
    exit 1
}

# Anvil
$anvilVersion = anvil --version 2>$null
if ($anvilVersion) {
    Write-Host "  Anvil : $anvilVersion" -ForegroundColor Green
} else {
    Write-Host "  Anvil : NON TROUVE - Installez Foundry" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================================
# 2. ACTIVATION DE L'ENVIRONNEMENT VIRTUEL
# ============================================================================

Write-Host "[2] Activation de l'environnement virtuel..." -ForegroundColor Yellow

if (Test-Path ".\venv\Scripts\Activate.ps1") {
    .\venv\Scripts\Activate.ps1
    Write-Host "  Environnement virtuel active" -ForegroundColor Green
} else {
    Write-Host "  Environnement virtuel non trouve - Creation..." -ForegroundColor Yellow
    python -m venv venv
    .\venv\Scripts\Activate.ps1
    Write-Host "  Environnement virtuel cree" -ForegroundColor Green
}

Write-Host ""

# ============================================================================
# 3. VERIFICATION DE DOCKER
# ============================================================================

Write-Host "[3] Verification de Docker..." -ForegroundColor Yellow

docker ps 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Docker Desktop n'est pas en cours d'execution" -ForegroundColor Red
    Write-Host "  Lancement de Docker Desktop..." -ForegroundColor Yellow
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -WindowStyle Minimized
    
    $timeout = 30
    $waited = 0
    while ($waited -lt $timeout) {
        Start-Sleep -Seconds 2
        $waited += 2
        docker ps 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Docker Desktop est pret !" -ForegroundColor Green
            break
        }
        Write-Host "  Attente... ($waited/$timeout secondes)" -ForegroundColor Gray
    }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Docker Desktop n'a pas demarre." -ForegroundColor Red
        exit 1
    }
}

Write-Host "  Docker est pret" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 4. FONCTIONS DE GESTION DES CONTENEURS
# ============================================================================

function Remove-Container {
    param([string]$Name)
    $exists = docker ps -a -q --filter "name=$Name" 2>$null
    if ($exists) {
        Write-Host "    Suppression de l'ancien conteneur $Name..." -ForegroundColor Gray
        docker rm -f $Name 2>$null
        return $true
    }
    return $false
}

function Start-Container {
    param(
        [string]$Name,
        [string]$Image,
        [string]$Ports,
        [hashtable]$Env = @{},
        [string]$Command = ""
    )
    
    Write-Host "    Demarrage de $Name..." -ForegroundColor Gray
    
    # Supprimer l'ancien conteneur
    Remove-Container $Name
    
    # Construire la commande
    $cmd = "docker run -d --name $Name $Ports"
    
    # Ajouter les variables d'environnement
    foreach ($key in $Env.Keys) {
        $cmd += " -e $key=$($Env[$key])"
    }
    
    # Ajouter l'image et la commande
    $cmd += " $Image $Command"
    
    # Exécuter la commande
    Write-Host "    Commande : $cmd" -ForegroundColor Gray
    $result = Invoke-Expression $cmd 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "    $Name : demarre" -ForegroundColor Green
        return $true
    } else {
        Write-Host "    $Name : ERREUR - $result" -ForegroundColor Red
        return $false
    }
}

# ============================================================================
# 5. DEMARRAGE DES SERVICES DOCKER
# ============================================================================

Write-Host "[4] Demarrage des services Docker..." -ForegroundColor Yellow

# Arrêter les services existants
Write-Host "  Arret des services existants..." -ForegroundColor Gray
docker compose down 2>$null

# Nettoyer les conteneurs orphelins
Write-Host "  Nettoyage des conteneurs..." -ForegroundColor Gray
$orphaned = docker ps -a -q --filter "name=pipeline_" 2>$null
if ($orphaned) {
    docker rm -f $orphaned 2>$null
    Write-Host "    $($orphaned.Count) conteneurs supprimes" -ForegroundColor Gray
}

# Redis
$redisOk = Start-Container -Name "pipeline_redis" -Image "redis:7-alpine" -Ports "-p 6379:6379"

# PostgreSQL
$postgresOk = Start-Container -Name "pipeline_postgres" -Image "postgres:14-alpine" -Ports "-p 5432:5432" -Env @{
    "POSTGRES_DB" = "pipeline"
    "POSTGRES_USER" = "pipeline"
    "POSTGRES_PASSWORD" = "pipeline"
}

if (-not $redisOk -or -not $postgresOk) {
    Write-Host "  Erreur lors du demarrage des services Docker" -ForegroundColor Red
    Write-Host "  Veuillez verifier que Docker fonctionne correctement." -ForegroundColor Yellow
    exit 1
}

Write-Host "  Services Docker demarres" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 6. DEMARRAGE DE ANVIL (LOCAL)
# ============================================================================

Write-Host "[5] Demarrage de Anvil..." -ForegroundColor Yellow

# Vérifier si Anvil tourne déjà
$anvilRunning = $false
try {
    $body = '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'
    $response = Invoke-WebRequest -Uri "http://localhost:8545" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 2
    if ($response.Content -match "0x4c72d" -or $response.Content -match "0x4c7a9") {
        $anvilRunning = $true
        Write-Host "  Anvil est deja en cours d'execution" -ForegroundColor Green
    }
} catch {}

if (-not $anvilRunning) {
    Write-Host "  Lancement de Anvil dans un nouveau terminal..." -ForegroundColor Yellow
    
    # Lancer Anvil dans un nouveau terminal PowerShell
    Start-Process powershell -ArgumentList "-NoExit", "-Command", @"
Write-Host '============================================' -ForegroundColor Cyan
Write-Host '  Anvil - Smart Contract Dev Pipeline 2.0' -ForegroundColor Cyan
Write-Host '============================================' -ForegroundColor Cyan
Write-Host '  Listening on http://localhost:8545' -ForegroundColor Green
Write-Host '  Chain ID: 313133' -ForegroundColor Gray
Write-Host '  Press CTRL+C to stop' -ForegroundColor Yellow
Write-Host '============================================' -ForegroundColor Cyan
Write-Host ''
anvil --host 0.0.0.0 --port 8545 --chain-id 313133
"@
    
    Write-Host "  Anvil lance dans un nouveau terminal" -ForegroundColor Green
    Write-Host "  Attente du demarrage d'Anvil (8s)..." -ForegroundColor Gray
    Start-Sleep -Seconds 8
    
    # Vérifier si Anvil répond
    try {
        $body = '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'
        $response = Invoke-WebRequest -Uri "http://localhost:8545" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 3
        if ($response.Content -match "0x4c72d" -or $response.Content -match "0x4c7a9") {
            Write-Host "  Anvil : OK !" -ForegroundColor Green
        }
    } catch {
        Write-Host "  Anvil : demarrage en cours..." -ForegroundColor Yellow
    }
}

Write-Host ""

# ============================================================================
# 7. VERIFICATION DES SERVICES
# ============================================================================

Write-Host "[6] Verification des services..." -ForegroundColor Yellow

function Test-Service {
    param(
        [string]$Name,
        [scriptblock]$Check,
        [int]$MaxRetries = 15,
        [int]$Delay = 2
    )
    
    $attempt = 0
    while ($attempt -lt $MaxRetries) {
        $attempt++
        try {
            $result = & $Check
            if ($result) {
                Write-Host "  $Name : OK" -ForegroundColor Green
                return $true
            }
        } catch {}
        if ($attempt -eq 1) {
            Write-Host "  $Name : en attente..." -ForegroundColor Gray
        }
        Start-Sleep -Seconds $Delay
    }
    Write-Host "  $Name : ERREUR" -ForegroundColor Red
    return $false
}

$redisOk = Test-Service -Name "Redis" -Check {
    $result = docker exec pipeline_redis redis-cli ping 2>$null
    $result -match "PONG"
}

$postgresOk = Test-Service -Name "PostgreSQL" -Check {
    docker exec pipeline_postgres psql -U pipeline -d pipeline -c "SELECT 1" 2>$null
    $LASTEXITCODE -eq 0
}

$anvilOk = Test-Service -Name "Anvil" -Check {
    try {
        $body = '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'
        $response = Invoke-WebRequest -Uri "http://localhost:8545" -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 3
        $response.Content -match "0x4c72d" -or $response.Content -match "0x4c7a9"
    } catch { $false }
}

Write-Host ""

# ============================================================================
# 8. PREPARATION DE L'ENVIRONNEMENT PYTHON
# ============================================================================

Write-Host "[7] Preparation de l'environnement Python..." -ForegroundColor Yellow

if (Test-Path "requirements.txt") {
    Write-Host "  Installation des dependances..." -ForegroundColor Gray
    pip install -r requirements.txt -q 2>$null
}

Write-Host "  Environnement pret" -ForegroundColor Green
Write-Host ""

# ============================================================================
# 9. LANCEMENT DE L'API
# ============================================================================

Write-Host "[8] Lancement de l'API FastAPI..." -ForegroundColor Yellow
Write-Host "  API : http://localhost:8000" -ForegroundColor Green
Write-Host "  Anvil : http://localhost:8545" -ForegroundColor Gray
Write-Host "  Redis : localhost:6379" -ForegroundColor Gray
Write-Host "  PostgreSQL : localhost:5432" -ForegroundColor Gray
Write-Host "  Press CTRL+C pour arreter" -ForegroundColor Gray
Write-Host ""

try {
    uvicorn src.api.web_dashboard:app --reload
} catch {
    Write-Host ""
    Write-Host "Erreur : $_" -ForegroundColor Red
    Read-Host "Press Enter pour quitter"
}