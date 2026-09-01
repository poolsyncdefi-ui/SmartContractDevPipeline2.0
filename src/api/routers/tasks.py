# src/api/routers/tasks.py
from fastapi import APIRouter, HTTPException
from src.api.schemas.requests import TaskApproveRequest
from src.api.schemas.responses import TaskStatusResponse
from src.git.git_sync_manager import GitSyncManager

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.post("/{task_id}/approve", response_model=TaskStatusResponse)
async def approve_task(
    task_id: str,
    payload: TaskApproveRequest
):
    """Approuve ou rejette une tâche."""
    if payload.approved:
        try:
            git = GitSyncManager()
            success = await git.commit_and_push(
                f"Approved task {task_id}",
                ["contracts/Vault.sol"]
            )
            if not success:
                raise HTTPException(status_code=500, detail="Git commit failed")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Approval failed: {e}")
    
    return TaskStatusResponse(
        task_id=task_id,
        status="approved" if payload.approved else "rejected"
    )