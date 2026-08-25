<#
.SYNOPSIS
    Genere des Gists GitHub - Version securisee avec gestion automatique du token
.DESCRIPTION
    Ce script scanne les fichiers du projet, les assemble dans un fichier unifie,
    les decoupe en parties de 0.9 MB et les uploade sur GitHub Gist.
    Le token GitHub est automatiquement recherche dans :
    1. Variable d'environnement GITHUB_TOKEN
    2. Fichier .env a la racine du projet
    3. Fichier de configuration project_config.json
    4. Saisie manuelle (en dernier recours)
#>

# ============================================================================
# CONFIGURATION
# ============================================================================

$CONFIG_PATH = "D:\Web3Projects\project_config.json"
$OUTPUT_FILE = "PROJECT_FULL.txt"

# Charger la configuration
$CONFIG = $null
if (Test-Path $CONFIG_PATH) {
    try {
        $configContent = Get-Content $CONFIG_PATH -Raw -Encoding UTF8
        $CONFIG = $configContent | ConvertFrom-Json
    } catch {
        Write-Host "WARNING: Erreur de lecture du fichier config, utilisation des valeurs par defaut" -ForegroundColor Yellow
    }
}

# Variables avec priorite a la config
$PROJECT_NAME = "SmartContractDevPipeline"
$GITHUB_TOKEN = $null
$PROJECT_PATHS = @()
$EXCLUDE_DIRS = @()
$EXCLUDE_PATTERNS = @()
$INCLUDE_PATTERNS = @()

if ($CONFIG) {
    # Nom du projet
    if ($CONFIG.PROJECT_NAME) { $PROJECT_NAME = $CONFIG.PROJECT_NAME }
    
    # Chemins a traiter
    if ($CONFIG.PROJECT_PATH) {
        $PROJECT_PATHS = @($CONFIG.PROJECT_PATH)
    }
    
    # Exclusions de dossiers
    if ($CONFIG.EXCLUDE_DIRS) { $EXCLUDE_DIRS = @($CONFIG.EXCLUDE_DIRS) }
    
    # Exclusions de motifs (chemins specifiques)
    if ($CONFIG.EXCLUDE_PATTERNS) { $EXCLUDE_PATTERNS = @($CONFIG.EXCLUDE_PATTERNS) }
    
    # Motifs d'inclusion
    if ($CONFIG.INCLUDE_PATTERNS) { $INCLUDE_PATTERNS = @($CONFIG.INCLUDE_PATTERNS) }
}

# Valeurs par defaut si non definies
if ($PROJECT_PATHS.Count -eq 0) {
    $PROJECT_PATHS = @("D:\Web3Projects\SmartContractDevPipeline")
}
if ($EXCLUDE_DIRS.Count -eq 0) {
    $EXCLUDE_DIRS = @("venv", "node_modules", "__pycache__", ".git", "logs", "reports")
}
if ($INCLUDE_PATTERNS.Count -eq 0) {
    $INCLUDE_PATTERNS = @("*.py", "*.js", "*.ts", "*.sol", "*.md", "*.json", "*.yaml", "*.yml")
}
if ($EXCLUDE_PATTERNS.Count -eq 0) {
    $EXCLUDE_PATTERNS = @("*.env", "*.env.local", "*.env.*.local", "*.secrets.json", "*.key", "*.pem", "*.p12", "*.pfx")
}

$MAX_GIST_SIZE_MB = 0.9  # 0.9 MB pour eviter les erreurs

# ============================================================================
# FONCTIONS
# ============================================================================

function Write-Info {
    param([string]$Message)
    Write-Host $Message
}

function Write-Success {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Green
}

function Write-ErrorMsg {
    param([string]$Message)
    Write-Host $Message -ForegroundColor Red
}

function Write-Gist-Link {
    param([string]$Url)
    Write-Host $Url -ForegroundColor Gray
}

function Is-Path-Excluded {
    param([string]$Path)
    
    # Verifier les exclusions de motifs (chemins specifiques)
    foreach ($pattern in $EXCLUDE_PATTERNS) {
        # Convertir les motifs glob en expressions regulieres simples
        $regexPattern = "^" + [regex]::Escape($pattern).Replace("\\\*", ".*").Replace("\*", ".*") + "$"
        if ($Path -match $regexPattern) {
            return $true
        }
        # Verifier si le chemin contient le motif
        $simplePattern = $pattern -replace "/\*$", "" -replace "\\\*$", ""
        if ($Path -like "*\$simplePattern\*" -or $Path -like "*\$simplePattern") {
            return $true
        }
    }
    return $false
}

function Get-ProjectFiles {
    Write-Info "Scanning files..."
    $allFiles = @()
    
    foreach ($path in $PROJECT_PATHS) {
        if (Test-Path $path) {
            $allFiles += Get-ChildItem -Path $path -Recurse -File -ErrorAction SilentlyContinue
        } else {
            Write-ErrorMsg "  Path not found: $path"
        }
    }
    
    $files = @()
    $excludedCount = 0
    
    foreach ($f in $allFiles) {
        $fullPath = $f.FullName
        $relativePath = $fullPath
        
        # Rendre le chemin relatif pour la comparaison
        foreach ($basePath in $PROJECT_PATHS) {
            if ($fullPath.StartsWith($basePath)) {
                $relativePath = $fullPath.Substring($basePath.Length + 1)
                break
            }
        }
        
        # Verifier les exclusions de motifs
        if (Is-Path-Excluded -Path $fullPath) {
            $excludedCount++
            continue
        }
        
        # Verifier les exclusions de dossiers
        $exclude = $false
        foreach ($dir in $EXCLUDE_DIRS) {
            if ($fullPath -match "\\$dir\\" -or $fullPath -match "\\$dir$") {
                $exclude = $true
                $excludedCount++
                break
            }
        }
        if ($exclude) { continue }
        
        # Verifier les motifs d'inclusion
        $included = $false
        foreach ($pattern in $INCLUDE_PATTERNS) {
            if ($f.Name -like $pattern) {
                $included = $true
                break
            }
        }
        if ($included) {
            $files += $f
        }
    }
    
    Write-Success "  Found $($files.Count) files ($excludedCount excluded)"
    return $files
}

function Generate-Unified-File {
    param([array]$Files)
    
    Write-Info "Generating unified file..."
    $outputPath = Join-Path $PROJECT_PATHS[0] $OUTPUT_FILE
    $totalSize = 0
    
    if (Test-Path $outputPath) { Remove-Item $outputPath -Force }
    
    $header = "PROJECT: $PROJECT_NAME`nDATE: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`nFILES: $($Files.Count)`n`n"
    $header | Out-File -FilePath $outputPath -Encoding UTF8
    $totalSize += $header.Length
    
    $processedCount = 0
    foreach ($f in $Files) {
        $processedCount++
        if ($f.Length -eq 0 -or $f.Length -gt 10MB) { continue }
        
        try {
            $content = Get-Content -Path $f.FullName -Raw -Encoding UTF8 -ErrorAction Stop
            if (-not $content -or $content -match '[\x00-\x08\x0B\x0C\x0E-\x1F]') { continue }
        } catch { continue }
        
        $separator = "`n=== $($f.FullName) ===`n`n$content`n"
        $separator | Out-File -FilePath $outputPath -Append -Encoding UTF8
        $totalSize += $separator.Length
    }
    
    $totalSizeMB = [Math]::Round($totalSize / 1MB, 2)
    Write-Success "  File created: $totalSizeMB MB"
    return @{ Path = $outputPath; Size = $totalSize }
}

function Upload-Gist {
    param([string]$Content, [int]$PartNum, [int]$TotalParts)
    
    # Nettoyer le contenu
    $cleanContent = $Content -replace '[\x00-\x08\x0B\x0C\x0E-\x1F]', ''
    $cleanContent = $cleanContent -replace '[^\x00-\x7F]', ''
    $cleanContent = $cleanContent -replace '[\x00-\x1F\x7F]', ''
    
    $filesDict = @{
        "PROJECT_PART_$("{0:D3}" -f $PartNum).txt" = @{ content = $cleanContent }
        "README.txt" = @{ content = "# $PROJECT_NAME - Part $PartNum/$TotalParts" }
    }
    
    $data = @{
        description = "$PROJECT_NAME - Part $PartNum/$TotalParts"
        public = $false
        files = $filesDict
    } | ConvertTo-Json -Depth 10 -Compress
    
    $headers = @{
        Authorization = "token $GITHUB_TOKEN"
        "Content-Type" = "application/json"
    }
    
    try {
        $response = Invoke-RestMethod -Uri "https://api.github.com/gists" -Method Post -Headers $headers -Body $data -TimeoutSec 60
        return $response.html_url
    } catch {
        return $null
    }
}

function Split-And-Upload {
    param([string]$FilePath, [int]$FileSize)
    
    Write-Info "Uploading to Gists..."
    
    try {
        $headers = @{ Authorization = "token $GITHUB_TOKEN" }
        $user = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers
        Write-Success "  Connected as: $($user.login)"
    } catch {
        Write-ErrorMsg "  Token invalid"
        return $null
    }
    
    $content = Get-Content -Path $FilePath -Raw -Encoding UTF8
    $maxSize = $MAX_GIST_SIZE_MB * 1MB
    $nbGists = [Math]::Ceiling($FileSize / $maxSize)
    
    Write-Info "  Splitting into $nbGists parts"
    
    $results = @()
    $position = 0
    $partNum = 1
    $successCount = 0
    
    while ($position -lt $content.Length) {
        $chunkSize = [Math]::Min($maxSize, $content.Length - $position)
        $chunk = $content.Substring($position, $chunkSize)
        
        # Ne pas couper au milieu d'une ligne
        $lastNewline = $chunk.LastIndexOf("`n")
        if ($lastNewline -gt 0 -and $position + $lastNewline + 1 -lt $content.Length) {
            $chunk = $content.Substring($position, $lastNewline + 1)
        }
        
        $url = Upload-Gist -Content $chunk -PartNum $partNum -TotalParts $nbGists
        
        if ($url) {
            $results += @{ Part = $partNum; Url = $url }
            $successCount++
            Write-Gist-Link -Url $url
        } else {
            Write-ErrorMsg "  Failed to upload part $partNum"
        }
        
        $position += $chunk.Length
        $partNum++
    }
    
    if ($successCount -eq $nbGists) {
        Write-Success "  All $successCount Gists uploaded successfully!"
    } else {
        Write-ErrorMsg "  Partial upload: $successCount/$nbGists successful"
    }
    
    return $results
}

function Save-Index {
    param([array]$Results)
    if (-not $Results) { return }
    
    $indexFile = Join-Path $PROJECT_PATHS[0] "GISTS_INDEX.txt"
    $content = "$PROJECT_NAME`n"
    $content += "Date: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"
    $content += "Gists: $($Results.Count)`n`n"
    
    foreach ($r in ($Results | Sort-Object Part)) {
        $content += "$($r.Url)`n"
    }
    
    $content | Out-File -FilePath $indexFile -Encoding UTF8
}

# ============================================================================
# FONCTION DE RECHERCHE DU TOKEN
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
    $projectPath = if ($PROJECT_PATHS.Count -gt 0) { $PROJECT_PATHS[0] } else { "." }
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
# MAIN
# ============================================================================

Clear-Host
Write-Host "================================================"
Write-Host " SHARE GISTS - $PROJECT_NAME"
Write-Host "================================================"
Write-Host ""

# Verification du token via la fonction avancee
$GITHUB_TOKEN = Get-GitHubToken -ConfigToken $CONFIG.GITHUB_TOKEN
if (-not $GITHUB_TOKEN) {
    Write-ErrorMsg "Cancelled: no GitHub token provided"
    Write-Host ""
    Write-Host "To use this script, you need to provide a GitHub token with 'gist' permission."
    Write-Host "Create one at: https://github.com/settings/tokens"
    exit
}

# Collecte des fichiers
$files = Get-ProjectFiles
if ($files.Count -eq 0) { 
    Write-ErrorMsg "No files found"
    exit 
}

# Generation du fichier unifie
$result = Generate-Unified-File -Files $files
if ($result.Size -eq 0) { 
    Write-ErrorMsg "Failed to generate file"
    exit 
}

# Upload vers Gists
$results = Split-And-Upload -FilePath $result.Path -FileSize $result.Size

if ($results) {
    Save-Index -Results $results
    
    Write-Host ""
    Write-Success "================================================"
    Write-Success "Done! $($results.Count) Gists created"
    Write-Success "================================================"
    Write-Host ""
    
    Write-Host "FILES:"
    Write-Host "  $($result.Path)" -ForegroundColor Gray
    Write-Host "  $(Join-Path $PROJECT_PATHS[0] 'GISTS_INDEX.txt')" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-ErrorMsg "Failed to upload"
}