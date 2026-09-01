# src/git/git_sync_manager.py
import asyncio
import httpx
from pathlib import Path
from typing import List, Optional
from src.config.settings import settings
from src.core.exceptions import GitSyncError

class GitSyncManager:
    """Gestionnaire des opérations Git et GitHub."""
    
    def __init__(self, project_path: Path = None, token: str = None):
        self.project_path = project_path or Path(settings.workspace_path)
        self.token = token or settings.github_token
        self._repo = None

    async def clone_or_pull(self, repo_url: str, branch: str = "main") -> Path:
        """Clone ou met à jour le repository."""
        # À implémenter avec GitPython
        return self.project_path

    async def create_branch(self, branch_name: str) -> bool:
        """Crée une nouvelle branche."""
        # À implémenter
        return True

    async def commit_and_push(self, message: str, files: List[str]) -> bool:
        """Commit et push les modifications."""
        # À implémenter
        return True

    async def publish_gist(self, filename: str, content: str, public: bool = False) -> str:
        """Publie un Gist sur GitHub."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.github.com/gists",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={
                        "description": f"Smart Contract Dev Pipeline 2.0 - {filename}",
                        "public": public,
                        "files": {filename: {"content": content}}
                    }
                )
                response.raise_for_status()
                return response.json().get("html_url", "")
        except Exception as e:
            raise