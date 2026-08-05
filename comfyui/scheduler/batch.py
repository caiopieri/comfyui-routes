"""
Gerenciador de Jobs em Batch (Modo Lote) do Scheduler da Casa Amarano.
Agrupa jobs do mesmo perfil em uma única sessão de container quente para economizar cold starts.
"""

from typing import List, Dict, Any, Tuple


class BatchJobGroup:
    def __init__(self, profile_key: Tuple[str, str, int]):
        # profile_key = (model, resolution, steps)
        self.model, self.resolution, self.steps = profile_key
        self.jobs: List[Dict[str, Any]] = []

    def add_job(self, job_data: Dict[str, Any]) -> None:
        self.jobs.append(job_data)

    def size(self) -> int:
        return len(self.jobs)


class BatchScheduler:
    def __init__(self):
        self.queues: Dict[Tuple[str, str, int], BatchJobGroup] = {}

    def enqueue_job(self, job_id: str, model: str, resolution: str, steps: int, payload: Dict[str, Any]) -> None:
        """Adiciona um job à fila de lote por perfil."""
        key = (model, resolution, steps)
        if key not in self.queues:
            self.queues[key] = BatchJobGroup(key)
        
        self.queues[key].add_job({"job_id": job_id, "payload": payload})

    def get_pending_batches(self) -> List[Dict[str, Any]]:
        """Retorna os lotes de jobs prontos para execução em container único."""
        batches = []
        for (model, resolution, steps), group in list(self.queues.items()):
            if group.size() > 0:
                batches.append({
                    "model": model,
                    "resolution": resolution,
                    "steps": steps,
                    "count": group.size(),
                    "jobs": group.jobs,
                })
        return batches

    def clear_batch(self, model: str, resolution: str, steps: int) -> None:
        key = (model, resolution, steps)
        if key in self.queues:
            del self.queues[key]
