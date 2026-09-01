# src/orchestration/workflow_engine.py
from typing import List, Dict, Set, Any
from collections import deque
from src.core.exceptions import TaskExecutionError

class WorkflowEngine:
    """Moteur d'exécution de DAG de tâches."""
    
    def __init__(self, bus=None, agents: Dict[str, Any] = None):
        self.bus = bus
        self.agents = agents or {}
        self.completed_tasks: Set[str] = set()
        self.tasks: List[Dict] = []

    def add_task(self, task: Dict) -> None:
        """Ajoute une tâche au workflow."""
        self.tasks.append(task)

    async def run_pipeline(self) -> Dict[str, Any]:
        """Exécute le pipeline complet."""
        order = self._resolve_order()
        results = {}
        for task in order:
            if not self._is_ready(task):
                raise TaskExecutionError(
                    task_id=task.get("id", "unknown"),
                    message="Dependencies not met"
                )
            result = await self._execute_node(task)
            results[task.get("id")] = result
            self.completed_tasks.add(task.get("id"))
        return results

    async def _execute_node(self, task: Dict) -> Dict:
        """Exécute une tâche individuelle."""
        agent_id = task.get("agent_id")
        if agent_id not in self.agents:
            raise TaskExecutionError(
                task_id=task.get("id", "unknown"),
                message=f"Agent '{agent_id}' not found"
            )
        agent = self.agents[agent_id]
        return await agent.execute_task(task)

    def _resolve_order(self) -> List[Dict]:
        """Tri topologique (algorithme de Kahn)."""
        graph = {t.get("id"): set(t.get("depends_on", [])) for t in self.tasks}
        in_degree = {t.get("id"): len(graph[t.get("id")]) for t in self.tasks}
        queue = deque([t for t in self.tasks if in_degree[t.get("id")] == 0])
        result = []
        
        while queue:
            node = queue.popleft()
            result.append(node)
            for other in self.tasks:
                if node.get("id") in graph[other.get("id")]:
                    in_degree[other.get("id")] -= 1
                    if in_degree[other.get("id")] == 0:
                        queue.append(other)
        
        if len(result) != len(self.tasks):
            raise ValueError("Cycle detected in DAG")
        return result

    def _is_ready(self, task: Dict) -> bool:
        """Vérifie si les dépendances sont satisfaites."""
        return all(dep in self.completed_tasks for dep in task.get("depends_on", []))