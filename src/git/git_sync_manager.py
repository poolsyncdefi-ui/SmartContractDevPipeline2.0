# ==============================================================================
# Smart Contract Dev Pipeline 2.0 - Git Sync Manager
# ==============================================================================
# Fichier: src/git/git_sync_manager.py
# Description: Gestionnaire des opérations Git et GitHub.
#              Gestion des commits, pushes, branches, tags, Gists et webhooks.
#              Support des conflits, des signatures GPG et des métriques.
#              Version refactorisée avec logger structuré et horodatages timezone-aware.
# ==============================================================================

import os
import subprocess
import tempfile
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
from datetime import datetime, timezone
import logging
import httpx
import asyncio
from enum import Enum

from src.config.settings import settings
from src.core.exceptions import GitSyncError, GitAuthenticationError, GistPublishError
from src.core.structured_logger import StructuredLogger, LogLevel, LogCategory
from src.core.adaptive_retry import AdaptiveRetry, RetryStrategy
from src.core.intelligent_cache import IntelligentCache, CacheStrategy

# ==============================================================================
# LOGGING
# ==============================================================================

logger = logging.getLogger(__name__)


# ==============================================================================
# ENUMS
# ==============================================================================

class GitOperation(str, Enum):
    """Types d'opérations Git."""
    INIT = "init"
    CLONE = "clone"
    COMMIT = "commit"
    PUSH = "push"
    PULL = "pull"
    FETCH = "fetch"
    MERGE = "merge"
    REBASE = "rebase"
    TAG = "tag"
    BRANCH = "branch"
    CHECKOUT = "checkout"
    STASH = "stash"


class GitStatus(str, Enum):
    """Statuts des fichiers Git."""
    UNTRACKED = "??"
    MODIFIED = " M"
    ADDED = "A "
    DELETED = "D "
    RENAMED = "R "
    COPIED = "C "
    UPDATED = "U "
    UNMERGED = "UU"


# ==============================================================================
# MANAGER GIT
# ==============================================================================

class GitSyncManager:
    """
    Gestionnaire des opérations Git et GitHub.
    
    Supporte:
    - Opérations Git de base (init, clone, commit, push, pull, fetch, merge)
    - Gestion des branches et tags
    - Gestion des conflits
    - Opérations GitHub (Gists, webhooks)
    - Signatures GPG
    - Métriques et statistiques
    - Cache intelligent pour les opérations coûteuses
    """
    
    def __init__(
        self,
        workspace_path: Optional[Path] = None,
        token: Optional[str] = None,
        username: Optional[str] = None,
        email: Optional[str] = None,
        gpg_key: Optional[str] = None,
        sign_commits: bool = False,
        max_retries: int = 3,
        cache_enabled: bool = True,
        cache_ttl: int = 300
    ):
        """
        Initialise le gestionnaire Git.
        
        Args:
            workspace_path: Chemin du workspace
            token: Token GitHub
            username: Nom d'utilisateur GitHub
            email: Email GitHub
            gpg_key: Clé GPG pour les signatures
            sign_commits: Signer les commits
            max_retries: Nombre maximum de tentatives
            cache_enabled: Activer le cache
            cache_ttl: Durée de vie du cache en secondes
        """
        # Valeurs par défaut sécurisées avec vérification d'attribut
        if hasattr(settings, 'pipeline') and hasattr(settings.pipeline, 'default_workspace'):
            default_workspace = settings.pipeline.default_workspace
        else:
            default_workspace = Path('./workspace')
        self.workspace_path = workspace_path or default_workspace
        
        # Token GitHub robuste (compatible SecretStr et str)
        self.token = self._extract_token(token)
        self.username = username or getattr(settings, 'github_username', 'unknown')
        self.email = email or f"{self.username}@users.noreply.github.com"
        self.gpg_key = gpg_key
        self.sign_commits = sign_commits
        self.max_retries = max_retries
        
        self._github_client: Optional[httpx.AsyncClient] = None
        
        # Logger structuré
        self._logger = StructuredLogger(
            component_name="GitSyncManager",
            log_level=LogLevel.INFO
        )
        self._logger.set_context(
            workspace=str(self.workspace_path),
            username=self.username
        )
        
        # Système de retry adaptatif pour les opérations réseau
        self._network_retry = AdaptiveRetry(
            base_delay=1.0,
            max_delay=30.0,
            max_retries=max_retries,
            strategy=RetryStrategy.EXPONENTIAL,
            jitter=True,
            retryable_exceptions=(httpx.TimeoutException, httpx.ConnectError)
        )
        
        # Cache intelligent pour les opérations coûteuses
        self._cache = IntelligentCache(
            default_ttl=cache_ttl,
            max_entries=200,
            strategy=CacheStrategy.ADAPTIVE,
            enable_metrics=True
        )
        if cache_enabled:
            self._cache.start()
        
        # Statistiques
        self._stats = {
            "total_operations": 0,
            "successful_operations": 0,
            "failed_operations": 0,
            "by_operation": {},
            "commits_count": 0,
            "pushes_count": 0,
            "pulls_count": 0,
            "gists_created": 0,
            "last_operation": None,
            "errors": 0
        }
        
        logger.info(f"GitSyncManager initialized: workspace={self.workspace_path}, username={self.username}")
    
    def _extract_token(self, token: Optional[str] = None) -> Optional[str]:
        """
        Extrait le token GitHub de manière robuste.
        
        Args:
            token: Token à extraire (peut être str, SecretStr ou None)
            
        Returns:
            Optional[str]: Token extrait
        """
        if token:
            if hasattr(token, 'get_secret_value'):
                try:
                    return token.get_secret_value()
                except Exception:
                    return str(token)
            return str(token)
        
        # Essayer de récupérer depuis les settings
        if hasattr(settings, 'github_token') and settings.github_token:
            token_val = settings.github_token
            if hasattr(token_val, 'get_secret_value'):
                try:
                    return token_val.get_secret_value()
                except Exception:
                    return str(token_val)
            return str(token_val)
        
        return None
    
    async def _ensure_github_client(self) -> None:
        """
        S'assure que le client GitHub est initialisé.
        """
        if self._github_client:
            return
        
        if not self.token:
            raise GitAuthenticationError(
                message="GitHub token is required for GitHub operations"
            )
        
        self._github_client = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            },
            timeout=30.0
        )
        
        self._logger.log_debug("GitHub client initialized", "github_client_initialized")
    
    def _update_stats(self, operation: GitOperation, success: bool) -> None:
        """
        Met à jour les statistiques.
        
        Args:
            operation: Type d'opération
            success: Succès de l'opération
        """
        self._stats["total_operations"] += 1
        if success:
            self._stats["successful_operations"] += 1
        else:
            self._stats["failed_operations"] += 1
            self._stats["errors"] += 1
        
        op_key = operation.value
        if op_key not in self._stats["by_operation"]:
            self._stats["by_operation"][op_key] = {"success": 0, "failed": 0}
        
        if success:
            self._stats["by_operation"][op_key]["success"] += 1
        else:
            self._stats["by_operation"][op_key]["failed"] += 1
        
        self._stats["last_operation"] = {
            "operation": operation.value,
            "success": success,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    # ==========================================================================
    # OPÉRATIONS GIT DE BASE
    # ==========================================================================
    
    def init_repo(
        self,
        repo_path: Path,
        remote_url: Optional[str] = None,
        default_branch: str = "main"
    ) -> bool:
        """
        Initialise un dépôt Git.
        
        Args:
            repo_path: Chemin du dépôt
            remote_url: URL du remote (optionnel)
            default_branch: Nom de la branche par défaut
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Initializing repository: {repo_path}",
            "git_init_start",
            repo_path=str(repo_path),
            default_branch=default_branch
        )
        
        try:
            repo_path.mkdir(parents=True, exist_ok=True)
            
            # Git init
            subprocess.run(
                ["git", "init", "-b", default_branch],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            # Configuration
            self._configure_repo(repo_path)
            
            if remote_url:
                subprocess.run(
                    ["git", "remote", "add", "origin", remote_url],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            
            self._logger.log_info(
                f"Repository initialized: {repo_path}",
                "git_init_completed",
                repo_path=str(repo_path)
            )
            logger.info(f"Repository initialized: {repo_path}")
            self._update_stats(GitOperation.INIT, True)
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to initialize repository: {e.stderr}",
                e,
                "git_init_failed",
                repo_path=str(repo_path)
            )
            logger.error(f"Failed to initialize repository: {e.stderr}")
            self._update_stats(GitOperation.INIT, False)
            raise GitSyncError(
                message=f"Failed to initialize repository: {e.stderr}",
                repo=str(repo_path),
                operation="init"
            )
    
    def _configure_repo(self, repo_path: Path) -> None:
        """
        Configure le dépôt Git.
        
        Args:
            repo_path: Chemin du dépôt
        """
        subprocess.run(
            ["git", "config", "user.name", self.username],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        subprocess.run(
            ["git", "config", "user.email", self.email],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if self.sign_commits and self.gpg_key:
            subprocess.run(
                ["git", "config", "user.signingkey", self.gpg_key],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
            subprocess.run(
                ["git", "config", "commit.gpgsign", "true"],
                cwd=repo_path,
                capture_output=True,
                text=True
            )
    
    def clone_repo(
        self,
        repo_url: str,
        target_path: Path,
        branch: Optional[str] = None,
        depth: Optional[int] = None
    ) -> bool:
        """
        Clone un dépôt Git.
        
        Args:
            repo_url: URL du dépôt
            target_path: Chemin cible
            branch: Branche à cloner
            depth: Profondeur du clone (shallow)
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Cloning repository: {repo_url}",
            "git_clone_start",
            repo_url=repo_url,
            target_path=str(target_path)
        )
        
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git", "clone", repo_url, str(target_path)]
            
            if branch:
                cmd.extend(["-b", branch])
            
            if depth:
                cmd.extend(["--depth", str(depth)])
            
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._configure_repo(target_path)
            
            self._logger.log_info(
                f"Repository cloned: {repo_url} -> {target_path}",
                "git_clone_completed",
                repo_url=repo_url,
                target_path=str(target_path)
            )
            logger.info(f"Repository cloned: {repo_url} -> {target_path}")
            self._update_stats(GitOperation.CLONE, True)
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to clone repository: {e.stderr}",
                e,
                "git_clone_failed",
                repo_url=repo_url
            )
            logger.error(f"Failed to clone repository: {e.stderr}")
            self._update_stats(GitOperation.CLONE, False)
            raise GitSyncError(
                message=f"Failed to clone repository: {e.stderr}",
                repo=repo_url,
                operation="clone"
            )
    
    def commit(
        self,
        repo_path: Path,
        message: str,
        files: Optional[List[str]] = None,
        all_files: bool = False,
        sign: Optional[bool] = None
    ) -> str:
        """
        Committe les changements.
        
        Args:
            repo_path: Chemin du dépôt
            message: Message de commit
            files: Fichiers à committer (optionnel)
            all_files: Committer tous les fichiers
            sign: Signer le commit
            
        Returns:
            str: Hash du commit
        """
        self._logger.log_info(
            f"Creating commit: {message[:50]}",
            "git_commit_start",
            repo_path=str(repo_path),
            all_files=all_files
        )
        
        try:
            # Ajouter les fichiers
            if files:
                subprocess.run(
                    ["git", "add"] + [str(f) for f in files],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            elif all_files:
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            
            # Commit
            cmd = ["git", "commit", "-m", message]
            
            sign_commit = sign if sign is not None else self.sign_commits
            if sign_commit:
                cmd.append("-S")
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            # Extraire le hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            commit_hash = hash_result.stdout.strip()
            
            self._stats["commits_count"] += 1
            self._update_stats(GitOperation.COMMIT, True)
            
            self._logger.log_info(
                f"Commit created: {commit_hash[:8]}",
                "git_commit_completed",
                commit_hash=commit_hash[:8],
                message=message[:100]
            )
            logger.info(f"Commit created: {commit_hash[:8]} - {message}")
            return commit_hash
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to commit: {e.stderr}",
                e,
                "git_commit_failed",
                repo_path=str(repo_path)
            )
            logger.error(f"Failed to commit: {e.stderr}")
            self._update_stats(GitOperation.COMMIT, False)
            raise GitSyncError(
                message=f"Failed to commit: {e.stderr}",
                repo=str(repo_path),
                operation="commit"
            )
    
    def push(
        self,
        repo_path: Path,
        remote: str = "origin",
        branch: str = "main",
        force: bool = False,
        set_upstream: bool = False
    ) -> bool:
        """
        Pousse les changements vers le remote.
        
        Args:
            repo_path: Chemin du dépôt
            remote: Nom du remote
            branch: Branche
            force: Force push
            set_upstream: Définir l'upstream
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Pushing to {remote}/{branch}",
            "git_push_start",
            repo_path=str(repo_path),
            remote=remote,
            branch=branch,
            force=force
        )
        
        try:
            cmd = ["git", "push"]
            
            if force:
                cmd.append("--force")
            
            if set_upstream:
                cmd.extend(["-u", remote, branch])
            else:
                cmd.extend([remote, branch])
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._stats["pushes_count"] += 1
            self._update_stats(GitOperation.PUSH, True)
            
            self._logger.log_info(
                f"Pushed to {remote}/{branch}",
                "git_push_completed",
                remote=remote,
                branch=branch
            )
            logger.info(f"Pushed to {remote}/{branch}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to push: {e.stderr}",
                e,
                "git_push_failed",
                remote=remote,
                branch=branch
            )
            logger.error(f"Failed to push: {e.stderr}")
            self._update_stats(GitOperation.PUSH, False)
            raise GitSyncError(
                message=f"Failed to push: {e.stderr}",
                repo=str(repo_path),
                operation="push"
            )
    
    def pull(
        self,
        repo_path: Path,
        remote: str = "origin",
        branch: str = "main",
        rebase: bool = False
    ) -> bool:
        """
        Tire les changements depuis le remote.
        
        Args:
            repo_path: Chemin du dépôt
            remote: Nom du remote
            branch: Branche
            rebase: Utiliser rebase au lieu de merge
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Pulling from {remote}/{branch}",
            "git_pull_start",
            repo_path=str(repo_path),
            remote=remote,
            branch=branch,
            rebase=rebase
        )
        
        try:
            cmd = ["git", "pull"]
            
            if rebase:
                cmd.append("--rebase")
            
            cmd.extend([remote, branch])
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._stats["pulls_count"] += 1
            self._update_stats(GitOperation.PULL, True)
            
            self._logger.log_info(
                f"Pulled from {remote}/{branch}",
                "git_pull_completed",
                remote=remote,
                branch=branch
            )
            logger.info(f"Pulled from {remote}/{branch}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to pull: {e.stderr}",
                e,
                "git_pull_failed",
                remote=remote,
                branch=branch
            )
            logger.error(f"Failed to pull: {e.stderr}")
            self._update_stats(GitOperation.PULL, False)
            raise GitSyncError(
                message=f"Failed to pull: {e.stderr}",
                repo=str(repo_path),
                operation="pull"
            )
    
    def fetch(
        self,
        repo_path: Path,
        remote: str = "origin",
        prune: bool = True
    ) -> bool:
        """
        Récupère les changements depuis le remote.
        
        Args:
            repo_path: Chemin du dépôt
            remote: Nom du remote
            prune: Supprimer les branches distantes supprimées
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_debug(
            f"Fetching from {remote}",
            "git_fetch_start",
            remote=remote
        )
        
        try:
            cmd = ["git", "fetch", remote]
            
            if prune:
                cmd.append("--prune")
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._update_stats(GitOperation.FETCH, True)
            self._logger.log_debug(f"Fetched from {remote}", "git_fetch_completed")
            logger.info(f"Fetched from {remote}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to fetch: {e.stderr}",
                e,
                "git_fetch_failed",
                remote=remote
            )
            logger.error(f"Failed to fetch: {e.stderr}")
            self._update_stats(GitOperation.FETCH, False)
            raise GitSyncError(
                message=f"Failed to fetch: {e.stderr}",
                repo=str(repo_path),
                operation="fetch"
            )
    
    # ==========================================================================
    # GESTION DES BRANCHES
    # ==========================================================================
    
    def create_branch(
        self,
        repo_path: Path,
        branch_name: str,
        source_branch: Optional[str] = None,
        checkout: bool = True
    ) -> bool:
        """
        Crée une nouvelle branche.
        
        Args:
            repo_path: Chemin du dépôt
            branch_name: Nom de la branche
            source_branch: Branche source (optionnel)
            checkout: Basculer sur la nouvelle branche
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Creating branch: {branch_name}",
            "git_branch_create_start",
            branch_name=branch_name,
            source_branch=source_branch
        )
        
        try:
            cmd = ["git", "branch", branch_name]
            
            if source_branch:
                cmd.append(source_branch)
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            if checkout:
                subprocess.run(
                    ["git", "checkout", branch_name],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            
            self._update_stats(GitOperation.BRANCH, True)
            self._logger.log_info(
                f"Branch created: {branch_name}",
                "git_branch_created",
                branch_name=branch_name
            )
            logger.info(f"Branch created: {branch_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to create branch: {e.stderr}",
                e,
                "git_branch_create_failed",
                branch_name=branch_name
            )
            logger.error(f"Failed to create branch: {e.stderr}")
            self._update_stats(GitOperation.BRANCH, False)
            raise GitSyncError(
                message=f"Failed to create branch: {e.stderr}",
                repo=str(repo_path),
                operation="branch"
            )
    
    def delete_branch(
        self,
        repo_path: Path,
        branch_name: str,
        force: bool = False
    ) -> bool:
        """
        Supprime une branche.
        
        Args:
            repo_path: Chemin du dépôt
            branch_name: Nom de la branche
            force: Force la suppression
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Deleting branch: {branch_name}",
            "git_branch_delete_start",
            branch_name=branch_name,
            force=force
        )
        
        try:
            cmd = ["git", "branch", "-d" if not force else "-D", branch_name]
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._update_stats(GitOperation.BRANCH, True)
            self._logger.log_info(
                f"Branch deleted: {branch_name}",
                "git_branch_deleted",
                branch_name=branch_name
            )
            logger.info(f"Branch deleted: {branch_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to delete branch: {e.stderr}",
                e,
                "git_branch_delete_failed",
                branch_name=branch_name
            )
            logger.error(f"Failed to delete branch: {e.stderr}")
            self._update_stats(GitOperation.BRANCH, False)
            raise GitSyncError(
                message=f"Failed to delete branch: {e.stderr}",
                repo=str(repo_path),
                operation="branch"
            )
    
    def list_branches(self, repo_path: Path) -> List[Dict[str, str]]:
        """
        Liste les branches du dépôt.
        
        Args:
            repo_path: Chemin du dépôt
            
        Returns:
            List[Dict[str, str]]: Liste des branches
        """
        try:
            result = subprocess.run(
                ["git", "branch", "-a", "--format=%(refname:short)|%(objectname:short)"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            branches = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    branches.append({
                        "name": parts[0],
                        "hash": parts[1] if len(parts) > 1 else None
                    })
            
            self._logger.log_debug(
                f"Listed {len(branches)} branches",
                "git_branches_listed",
                count=len(branches)
            )
            
            return branches
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to list branches: {e.stderr}",
                e,
                "git_branch_list_failed"
            )
            logger.error(f"Failed to list branches: {e.stderr}")
            return []
    
    # ==========================================================================
    # GESTION DES TAGS
    # ==========================================================================
    
    def create_tag(
        self,
        repo_path: Path,
        tag_name: str,
        message: Optional[str] = None,
        sign: bool = False
    ) -> bool:
        """
        Crée un tag.
        
        Args:
            repo_path: Chemin du dépôt
            tag_name: Nom du tag
            message: Message du tag (optionnel)
            sign: Signer le tag
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Creating tag: {tag_name}",
            "git_tag_create_start",
            tag_name=tag_name
        )
        
        try:
            cmd = ["git", "tag"]
            
            if sign:
                cmd.append("-s")
            elif message:
                cmd.append("-a")
            
            cmd.append(tag_name)
            
            if message:
                cmd.extend(["-m", message])
            
            subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._update_stats(GitOperation.TAG, True)
            self._logger.log_info(
                f"Tag created: {tag_name}",
                "git_tag_created",
                tag_name=tag_name
            )
            logger.info(f"Tag created: {tag_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to create tag: {e.stderr}",
                e,
                "git_tag_create_failed",
                tag_name=tag_name
            )
            logger.error(f"Failed to create tag: {e.stderr}")
            self._update_stats(GitOperation.TAG, False)
            raise GitSyncError(
                message=f"Failed to create tag: {e.stderr}",
                repo=str(repo_path),
                operation="tag"
            )
    
    def push_tag(self, repo_path: Path, tag_name: str, remote: str = "origin") -> bool:
        """
        Pousse un tag vers le remote.
        
        Args:
            repo_path: Chemin du dépôt
            tag_name: Nom du tag
            remote: Nom du remote
            
        Returns:
            bool: True si réussi
        """
        self._logger.log_info(
            f"Pushing tag: {tag_name}",
            "git_tag_push_start",
            tag_name=tag_name,
            remote=remote
        )
        
        try:
            subprocess.run(
                ["git", "push", remote, tag_name],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._update_stats(GitOperation.PUSH, True)
            self._logger.log_info(
                f"Tag pushed: {tag_name}",
                "git_tag_pushed",
                tag_name=tag_name
            )
            logger.info(f"Tag pushed: {tag_name}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to push tag: {e.stderr}",
                e,
                "git_tag_push_failed",
                tag_name=tag_name
            )
            logger.error(f"Failed to push tag: {e.stderr}")
            self._update_stats(GitOperation.PUSH, False)
            raise GitSyncError(
                message=f"Failed to push tag: {e.stderr}",
                repo=str(repo_path),
                operation="push_tag"
            )
    
    # ==========================================================================
    # GESTION DES CONFLITS
    # ==========================================================================
    
    def get_status(self, repo_path: Path) -> Dict[str, str]:
        """
        Récupère le statut du dépôt.
        
        Args:
            repo_path: Chemin du dépôt
            
        Returns:
            Dict[str, str]: Statut des fichiers
        """
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            status = {}
            for line in result.stdout.strip().split('\n'):
                if line:
                    status[line[3:]] = line[:2]
            
            return status
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to get status: {e.stderr}",
                e,
                "git_status_failed"
            )
            logger.error(f"Failed to get status: {e.stderr}")
            return {}
    
    def has_conflicts(self, repo_path: Path) -> bool:
        """
        Vérifie si le dépôt a des conflits.
        
        Args:
            repo_path: Chemin du dépôt
            
        Returns:
            bool: True s'il y a des conflits
        """
        status = self.get_status(repo_path)
        has_conflict = any(val == GitStatus.UNMERGED.value for val in status.values())
        
        if has_conflict:
            self._logger.log_warning(
                "Conflicts detected in repository",
                "git_conflicts_detected",
                repo_path=str(repo_path)
            )
        
        return has_conflict
    
    def resolve_conflict(
        self,
        repo_path: Path,
        file_path: str,
        resolution: str = "theirs"
    ) -> bool:
        """
        Résout un conflit.
        
        Args:
            repo_path: Chemin du dépôt
            file_path: Chemin du fichier
            resolution: Stratégie de résolution ('ours', 'theirs', 'manual')
            
        Returns:
            bool: True si résolu
        """
        self._logger.log_info(
            f"Resolving conflict: {file_path} using {resolution}",
            "git_conflict_resolve_start",
            file_path=file_path,
            resolution=resolution
        )
        
        try:
            if resolution == "theirs":
                subprocess.run(
                    ["git", "checkout", "--theirs", file_path],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            elif resolution == "ours":
                subprocess.run(
                    ["git", "checkout", "--ours", file_path],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                    text=True
                )
            else:
                # Résolution manuelle
                return False
            
            # Ajouter le fichier résolu
            subprocess.run(
                ["git", "add", file_path],
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True
            )
            
            self._update_stats(GitOperation.MERGE, True)
            self._logger.log_info(
                f"Conflict resolved: {file_path}",
                "git_conflict_resolved",
                file_path=file_path,
                resolution=resolution
            )
            logger.info(f"Conflict resolved: {file_path} using {resolution}")
            return True
            
        except subprocess.CalledProcessError as e:
            self._logger.log_error(
                f"Failed to resolve conflict: {e.stderr}",
                e,
                "git_conflict_resolve_failed",
                file_path=file_path
            )
            logger.error(f"Failed to resolve conflict: {e.stderr}")
            self._update_stats(GitOperation.MERGE, False)
            return False
    
    # ==========================================================================
    # OPÉRATIONS GITHUB
    # ==========================================================================
    
    async def create_gist(
        self,
        content: str,
        filename: str,
        description: Optional[str] = None,
        public: bool = False
    ) -> Dict[str, Any]:
        """
        Crée un Gist sur GitHub.
        
        Args:
            content: Contenu du Gist
            filename: Nom du fichier
            description: Description du Gist
            public: Gist public ou privé
            
        Returns:
            Dict[str, Any]: Informations du Gist
            
        Raises:
            GistPublishError: Si la publication échoue
        """
        await self._ensure_github_client()
        
        self._logger.log_info(
            f"Creating gist: {filename}",
            "github_gist_create_start",
            filename=filename,
            public=public
        )
        
        data = {
            "description": description or f"Gist created at {datetime.now(timezone.utc).isoformat()}",
            "public": public,
            "files": {
                filename: {
                    "content": content
                }
            }
        }
        
        try:
            async def _create_gist():
                response = await self._github_client.post("/gists", json=data)
                response.raise_for_status()
                return response.json()
            
            result = await self._network_retry.execute_with_retry(_create_gist)
            
            self._stats["gists_created"] += 1
            self._update_stats(GitOperation.COMMIT, True)  # Reuse COMMIT for gists
            
            self._logger.log_info(
                f"Gist created: {result['html_url']}",
                "github_gist_created",
                gist_id=result["id"],
                url=result["html_url"]
            )
            logger.info(f"Gist created: {result['html_url']}")
            
            return {
                "id": result["id"],
                "url": result["html_url"],
                "raw_url": result["files"][filename]["raw_url"],
                "created_at": result["created_at"]
            }
            
        except httpx.HTTPStatusError as e:
            self._logger.log_error(
                f"Failed to create gist: {e.response.text}",
                e,
                "github_gist_create_failed",
                status_code=e.response.status_code
            )
            logger.error(f"Failed to create gist: {e.response.text}")
            self._update_stats(GitOperation.COMMIT, False)
            raise GistPublishError(
                filename=filename,
                message=e.response.text,
                status_code=e.response.status_code
            )
        except Exception as e:
            self._logger.log_error(
                f"Failed to create gist: {str(e)}",
                e,
                "github_gist_create_failed"
            )
            self._update_stats(GitOperation.COMMIT, False)
            raise GistPublishError(
                filename=filename,
                message=str(e)
            )
    
    async def update_gist(
        self,
        gist_id: str,
        content: str,
        filename: str
    ) -> Dict[str, Any]:
        """
        Met à jour un Gist existant.
        
        Args:
            gist_id: ID du Gist
            content: Nouveau contenu
            filename: Nom du fichier
            
        Returns:
            Dict[str, Any]: Informations du Gist
        """
        await self._ensure_github_client()
        
        self._logger.log_info(
            f"Updating gist: {gist_id}",
            "github_gist_update_start",
            gist_id=gist_id,
            filename=filename
        )
        
        data = {
            "files": {
                filename: {
                    "content": content
                }
            }
        }
        
        try:
            async def _update_gist():
                response = await self._github_client.patch(f"/gists/{gist_id}", json=data)
                response.raise_for_status()
                return response.json()
            
            result = await self._network_retry.execute_with_retry(_update_gist)
            
            self._update_stats(GitOperation.COMMIT, True)
            
            self._logger.log_info(
                f"Gist updated: {result['html_url']}",
                "github_gist_updated",
                gist_id=gist_id,
                url=result["html_url"]
            )
            logger.info(f"Gist updated: {result['html_url']}")
            
            return {
                "id": result["id"],
                "url": result["html_url"],
                "raw_url": result["files"][filename]["raw_url"],
                "updated_at": result["updated_at"]
            }
            
        except Exception as e:
            self._logger.log_error(
                f"Failed to update gist: {str(e)}",
                e,
                "github_gist_update_failed",
                gist_id=gist_id
            )
            logger.error(f"Failed to update gist: {str(e)}")
            self._update_stats(GitOperation.COMMIT, False)
            raise GitSyncError(
                message=f"Failed to update gist: {str(e)}",
                operation="update_gist"
            )
    
    async def get_gist(self, gist_id: str) -> Dict[str, Any]:
        """
        Récupère un Gist.
        
        Args:
            gist_id: ID du Gist
            
        Returns:
            Dict[str, Any]: Informations du Gist
        """
        await self._ensure_github_client()
        
        # Vérification du cache
        cache_key = f"gist:{gist_id}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            self._logger.log_debug(f"Gist cache hit: {gist_id}", "gist_cache_hit")
            return cached
        
        self._logger.log_debug(
            f"Getting gist: {gist_id}",
            "github_gist_get_start",
            gist_id=gist_id
        )
        
        try:
            async def _get_gist():
                response = await self._github_client.get(f"/gists/{gist_id}")
                response.raise_for_status()
                return response.json()
            
            result = await self._network_retry.execute_with_retry(_get_gist)
            
            # Mise en cache
            await self._cache.set(cache_key, result, ttl=300, tags=["gist"])
            
            return result
            
        except Exception as e:
            self._logger.log_error(
                f"Failed to get gist: {str(e)}",
                e,
                "github_gist_get_failed",
                gist_id=gist_id
            )
            logger.error(f"Failed to get gist: {str(e)}")
            raise GitSyncError(
                message=f"Failed to get gist: {str(e)}",
                operation="get_gist"
            )
    
    async def create_webhook(
        self,
        repo: str,
        webhook_url: str,
        events: List[str],
        secret: Optional[str] = None,
        active: bool = True
    ) -> Dict[str, Any]:
        """
        Crée un webhook sur un dépôt GitHub.
        
        Args:
            repo: Nom du dépôt (owner/repo)
            webhook_url: URL du webhook
            events: Événements déclencheurs
            secret: Secret pour la signature
            active: Webhook actif
            
        Returns:
            Dict[str, Any]: Informations du webhook
        """
        await self._ensure_github_client()
        
        self._logger.log_info(
            f"Creating webhook for {repo}",
            "github_webhook_create_start",
            repo=repo,
            url=webhook_url
        )
        
        data = {
            "name": "web",
            "active": active,
            "events": events,
            "config": {
                "url": webhook_url,
                "content_type": "json",
                "insecure_ssl": "0"
            }
        }
        
        if secret:
            data["config"]["secret"] = secret
        
        try:
            async def _create_webhook():
                response = await self._github_client.post(
                    f"/repos/{repo}/hooks",
                    json=data
                )
                response.raise_for_status()
                return response.json()
            
            result = await self._network_retry.execute_with_retry(_create_webhook)
            
            self._logger.log_info(
                f"Webhook created: {result['id']} for {repo}",
                "github_webhook_created",
                webhook_id=result["id"],
                repo=repo
            )
            logger.info(f"Webhook created: {result['id']} for {repo}")
            return result
            
        except Exception as e:
            self._logger.log_error(
                f"Failed to create webhook: {str(e)}",
                e,
                "github_webhook_create_failed",
                repo=repo
            )
            logger.error(f"Failed to create webhook: {str(e)}")
            raise GitSyncError(
                message=f"Failed to create webhook: {str(e)}",
                operation="create_webhook"
            )
    
    # ==========================================================================
    # OPÉRATIONS DE FICHIERS
    # ==========================================================================
    
    def save_artifact_to_workspace(
        self,
        content: str,
        filename: str,
        subpath: Optional[str] = None,
        create_dir: bool = True
    ) -> Path:
        """
        Sauvegarde un artefact dans le workspace.
        
        Args:
            content: Contenu de l'artefact
            filename: Nom du fichier
            subpath: Sous-chemin optionnel
            create_dir: Créer le dossier parent
            
        Returns:
            Path: Chemin du fichier sauvegardé
        """
        target_path = self.workspace_path
        if subpath:
            target_path = target_path / subpath
        
        if create_dir:
            target_path.mkdir(parents=True, exist_ok=True)
        
        file_path = target_path / filename
        file_path.write_text(content, encoding='utf-8')
        
        self._logger.log_info(
            f"Artifact saved: {file_path}",
            "artifact_saved",
            file_path=str(file_path),
            size_bytes=len(content)
        )
        logger.info(f"Artifact saved: {file_path}")
        return file_path
    
    def read_artifact_from_workspace(self, file_path: Path) -> str:
        """
        Lit un artefact depuis le workspace.
        
        Args:
            file_path: Chemin du fichier
            
        Returns:
            str: Contenu du fichier
            
        Raises:
            FileNotFoundError: Si le fichier n'existe pas
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        content = file_path.read_text(encoding='utf-8')
        
        self._logger.log_debug(
            f"Artifact read: {file_path}",
            "artifact_read",
            file_path=str(file_path),
            size_bytes=len(content)
        )
        
        return content
    
    def delete_artifact_from_workspace(self, file_path: Path) -> bool:
        """
        Supprime un artefact du workspace.
        
        Args:
            file_path: Chemin du fichier
            
        Returns:
            bool: True si supprimé
        """
        if file_path.exists():
            file_path.unlink()
            self._logger.log_info(
                f"Artifact deleted: {file_path}",
                "artifact_deleted",
                file_path=str(file_path)
            )
            logger.info(f"Artifact deleted: {file_path}")
            return True
        return False
    
    def list_workspace_files(
        self,
        subpath: Optional[str] = None,
        pattern: Optional[str] = None
    ) -> List[Path]:
        """
        Liste les fichiers du workspace.
        
        Args:
            subpath: Sous-chemin optionnel
            pattern: Pattern de recherche (glob)
            
        Returns:
            List[Path]: Liste des fichiers
        """
        target_path = self.workspace_path
        if subpath:
            target_path = target_path / subpath
        
        if not target_path.exists():
            return []
        
        if pattern:
            return list(target_path.glob(pattern))
        
        return list(target_path.rglob("*"))
    
    # ==========================================================================
    # STATISTIQUES
    # ==========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Retourne les statistiques du gestionnaire.
        
        Returns:
            Dict[str, Any]: Statistiques
        """
        cache_metrics = self._cache.get_metrics()
        
        return {
            **self._stats,
            "workspace_path": str(self.workspace_path),
            "username": self.username,
            "sign_commits": self.sign_commits,
            "has_gpg_key": bool(self.gpg_key),
            "cache_metrics": cache_metrics,
            "success_rate": (
                self._stats["successful_operations"] / self._stats["total_operations"]
                if self._stats["total_operations"] > 0 else 0
            )
        }
    
    async def clear_cache(self) -> int:
        """
        Vide le cache.
        
        Returns:
            int: Nombre d'entrées supprimées
        """
        cache_metrics = self._cache.get_metrics()
        cache_size = cache_metrics.get("total_entries", 0)
        await self._cache.clear()
        self._logger.log_info(f"Cache cleared ({cache_size} entries)", "cache_cleared")
        return cache_size
    
    # ==========================================================================
    # FERMETURE
    # ==========================================================================
    
    async def close(self) -> None:
        """
        Ferme le client GitHub.
        """
        await self._cache.stop()
        
        if self._github_client:
            await self._github_client.aclose()
            self._github_client = None
        
        self._logger.log_info("GitSyncManager closed", "manager_closed")
        logger.info("GitSyncManager closed")