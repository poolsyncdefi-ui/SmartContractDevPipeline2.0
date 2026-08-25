# ==============================================================================
# git_push.ps1 - Push automatique vers GitHub avec gestion du token
# ==============================================================================

<#
.SYNOPSIS
    Push les modifications vers GitHub en utilisant le token du projet
.DESCRIPTION
    Ce script utilise la même logique de récupération de token que share_gists.ps1
    pour s'authentifier sur GitHub. Le token est recherché dans :
    1. Variable d'environnement GITHUB_TOKEN
    2. Fichier .env a la racine du projet
    3. Fichier de configuration project_config.json
    4. Saisie manuelle (en dernier recours)
#>

# ============================================================================
# CONFIGURATION
# ============================================================================

$CONFIG_PATH = "D:\Web3Projects\project_config.json"

# Charger la configuration
$CONFIG = $null
if (Test-Path $CONFIG_PATH) {
    try {
        $configContent = Get-Content $CONFIG_PATH -Raw -Encoding UTF8
        $CONFIG = $configContent | ConvertFrom-Json
    } catch {
        Write-Host "WARNING: Erreur de lecture du fichier config" -ForegroundColor Yellow
    }
}

# Variables
$PROJECT_NAME = "SmartContractDevPipeline"
$GITHUB_TOKEN = $null

# Extraire les informations de la config
if ($CONFIG) {
    if ($CONFIG.PROJECT_NAME) { $PROJECT_NAME = $CONFIG.PROJECT_NAME }
}

# ============================================================================
# FONCTION DE RECHERCHE DU TOKEN (copiée de share_gists.ps1)
# ============================================================================

function Get-GitHubToken {
    param(
        [string]$ConfigToken
    )
    
    Write-Host "Searching for GitHub token..." -ForegroundColor Cyan
    
    # 1. Priorite a la variable d'environnement
    if ($env:GITHUB_TOKEN) {
        Write-Host "  Token loaded from environment variable GITHUB_TOKEN" -ForegroundColor Green
        return $env:GITHUB_TOKEN
    }
    
    # 2. Sinon, essayer de charger depuis .env a la racine du projet
    $projectPath = "."
    $envPath = Join-Path $projectPath ".env"
    Write-Host "  Looking for .env file in: $envPath" -ForegroundColor Gray
    
    if (Test-Path $envPath) {
        try {
            Write-Host "  .env file found, reading..." -ForegroundColor Gray
            $envContent = Get-Content $envPath -Raw -Encoding UTF8
            $match = [regex]::Match($envContent, 'GITHUB_TOKEN\s*=\s*([^\r\n]+)')
            if ($match.Success) {
                $token = $match.Groups[1].Value.Trim()
                if ($token -and $token -ne 'votre_token_ici' -and $token -ne 'ghp_.............') {
                    Write-Host "  Token loaded from .env file" -ForegroundColor Green
                    return $token
                } else {
                    Write-Host "  Token found but seems to be a placeholder" -ForegroundColor Yellow
                }
            } else {
                Write-Host "  No GITHUB_TOKEN line found in .env" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "  Error reading .env file: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  .env file not found" -ForegroundColor Yellow
    }
    
    # 3. Sinon, utiliser le token de la config si valide
    if ($ConfigToken -and $ConfigToken -notmatch "^ghp_\.\.\." -and $ConfigToken -ne '${GITHUB_TOKEN}') {
        Write-Host "  Token loaded from configuration file (please migrate to .env)" -ForegroundColor Yellow
        return $ConfigToken
    }
    
    # 4. Sinon, demander a l'utilisateur
    Write-Host "  No token found automatically" -ForegroundColor Yellow
    Write-Host "  Suggestions:" -ForegroundColor Gray
    Write-Host "     - Set environment variable GITHUB_TOKEN" -ForegroundColor Gray
    Write-Host "     - Add GITHUB_TOKEN=your_token in .env file" -ForegroundColor Gray
    Write-Host "     - Configure token in project_config.json" -ForegroundColor Gray
    Write-Host ""
    
    $token = Read-Host -Prompt "  Enter your GitHub token (or leave empty to cancel)"
    if ($token) { 
        Write-Host "  Token entered manually" -ForegroundColor Green
        return $token 
    }
    return $null
}

# ============================================================================
# VERIFICATION DE L'ENVIRONNEMENT GIT
# ============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Git Push - $PROJECT_NAME" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Récupérer le token
$GITHUB_TOKEN = Get-GitHubToken -ConfigToken $CONFIG.GITHUB_TOKEN
if (-not $GITHUB_TOKEN) {
    Write-ErrorMsg "Cancelled: no GitHub token provided"
    Write-Host ""
    Write-Host "To use this script, you need to provide a GitHub token."
    Write-Host "Create one at: https://github.com/settings/tokens"
    exit
}

Write-Host ""
Write-Host "[1] Verification de l'environnement Git..." -ForegroundColor Yellow

# Vérifier que git est installé
$gitVersion = git --version 2>$null
if ($gitVersion) {
    Write-Host "  Git : $gitVersion" -ForegroundColor Green
} else {
    Write-Host "  Git : NON TROUVE" -ForegroundColor Red
    exit 1
}

# Vérifier le remote
$remoteUrl = git remote get-url origin 2>$null
if (-not $remoteUrl) {
    Write-Host "  Remote 'origin' non configure" -ForegroundColor Red
    Write-Host "  Configuration du remote avec token..." -ForegroundColor Yellow
    git remote add origin https://$($GITHUB_TOKEN)@github.com/poolsyncdefi-ui/SmartContractDevPipeline2.0.git
    Write-Host "  Remote configure" -ForegroundColor Green
} else {
    # Mettre à jour le remote avec le token
    Write-Host "  Mise a jour du remote avec le token..." -ForegroundColor Gray
    git remote set-url origin https://$($GITHUB_TOKEN)@github.com/poolsyncdefi-ui/SmartContractDevPipeline2.0.git
    Write-Host "  Remote mis a jour" -ForegroundColor Green
}

Write-Host ""

# ============================================================================
# VERIFICATION DES MODIFICATIONS
# ============================================================================

Write-Host "[2] Verification des modifications..." -ForegroundColor Yellow

# Voir les fichiers modifiés
$modifiedFiles = git status --porcelain
if (-not $modifiedFiles) {
    Write-Host "  Aucun fichier modifie" -ForegroundColor Green
    Write-Host "  Rien a commiter." -ForegroundColor Yellow
    exit 0
}

Write-Host "  Fichiers modifies :" -ForegroundColor Gray
$modifiedFiles | ForEach-Object {
    $status = $_.Substring(0, 2).Trim()
    $file = $_.Substring(3)
    $statusText = switch ($status) {
        "M" { "Modifie" }
        "A" { "Ajoute" }
        "D" { "Supprime" }
        "R" { "Renomme" }
        "??" { "Non suivi" }
        default { $status }
    }
    Write-Host "    [$statusText] $file" -ForegroundColor Gray
}

Write-Host ""

# ============================================================================
# PREPARATION DU COMMIT
# ============================================================================

Write-Host "[3] Preparation du commit..." -ForegroundColor Yellow

$defaultMessage = "Update $PROJECT_NAME - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
Write-Host "  Message par defaut : $defaultMessage" -ForegroundColor Gray

$commitMessage = Read-Host -Prompt "  Message de commit (Enter pour defaut)"
if (-not $commitMessage) {
    $commitMessage = $defaultMessage
}

Write-Host "  Message : $commitMessage" -ForegroundColor Green
Write-Host ""

# ============================================================================
# EXECUTION DU COMMIT
# ============================================================================

Write-Host "[4] Execution du commit..." -ForegroundColor Yellow

# Ajouter tous les fichiers
Write-Host "  Ajout des fichiers..." -ForegroundColor Gray
git add .

# Commit
Write-Host "  Commit..." -ForegroundColor Gray
$commitResult = git commit -m $commitMessage 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "  Erreur lors du commit" -ForegroundColor Red
    Write-Host "  $commitResult" -ForegroundColor Red
    exit 1
}
Write-Host "  Commit reussi" -ForegroundColor Green

Write-Host ""

# ============================================================================
# PUSH
# ============================================================================

Write-Host "[5] Push vers GitHub..." -ForegroundColor Yellow

# Déterminer la branche
$branch = git branch --show-current
if (-not $branch) {
    $branch = "main"
}

Write-Host "  Branche : $branch" -ForegroundColor Gray

# Push (le remote est déjà configuré avec le token)
Write-Host "  Push en cours..." -ForegroundColor Gray
$pushResult = git push origin $branch 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "  Push reussi !" -ForegroundColor Green
    $pushSuccess = $true
} else {
    Write-Host "  Erreur lors du push" -ForegroundColor Red
    Write-Host "  $pushResult" -ForegroundColor Red
    
    # Tentative avec upstream
    Write-Host "  Tentative avec upstream..." -ForegroundColor Yellow
    $pushResult = git push --set-upstream origin $branch 2>&1
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  Push reussi !" -ForegroundColor Green
        $pushSuccess = $true
    } else {
        Write-Host "  Erreur lors du push avec upstream" -ForegroundColor Red
        Write-Host "  $pushResult" -ForegroundColor Red
        $pushSuccess = $false
    }
}

Write-Host ""

# ============================================================================
# RESUME
# ============================================================================

Write-Host "============================================================" -ForegroundColor Cyan
if ($pushSuccess) {
    Write-Host "  Git Push : SUCCES" -ForegroundColor Green
} else {
    Write-Host "  Git Push : ECHEC" -ForegroundColor Red
}
Write-Host "  Branche : $branch" -ForegroundColor Gray
Write-Host "  Message : $commitMessage" -ForegroundColor Gray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not $pushSuccess) {
    Write-Host "Diagnostic :" -ForegroundColor Yellow
    Write-Host "  1. Verifiez votre connexion internet" -ForegroundColor Gray
    Write-Host "  2. Verifiez que le token a les permissions 'repo' et 'workflow'" -ForegroundColor Gray
    Write-Host "  3. Verifiez le remote : git remote -v" -ForegroundColor Gray
    Write-Host ""
}