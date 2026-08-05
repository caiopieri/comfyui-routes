"""
Algoritmo do Roteador de GPU (Scheduler) da Casa Amarano.
Implementa o filtro rígido de VRAM, estimativa por histórico medido,
cálculo de score (custo + lambda * tempo) e detecção de container quente.
"""

from typing import Dict, List, Any, Optional
from comfyui.modal_backend.config import (
    GPU_SPECS,
    MODEL_VRAM_REQUIREMENTS,
    DEFAULT_LAMBDA_HOURLY_VAL,
)
from comfyui.scheduler.seed_data import get_seed_estimate
from comfyui.scheduler.db import SchedulerDB
from comfyui.scheduler.budget import BudgetManager


class GPURouter:
    def __init__(
        self,
        db: Optional[SchedulerDB] = None,
        budget_manager: Optional[BudgetManager] = None,
        default_lambda: float = DEFAULT_LAMBDA_HOURLY_VAL,
    ):
        self.db = db or SchedulerDB()
        self.budget_manager = budget_manager or BudgetManager(self.db)
        self.default_lambda = default_lambda

    def route_job(
        self,
        model: str,
        resolution: str = "1024x1024",
        steps: int = 30,
        lambda_val: Optional[float] = None,
        warm_gpus: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """
        Escolhe a melhor GPU para a tarefa com base na VRAM, custo medido e preferência de tempo.
        
        Args:
            model: Nome do modelo (ex: 'sdxl', 'flux_dev', 'wan_2_2_14b')
            resolution: Resolução pretendida (ex: '1024x1024', '1280x720')
            steps: Número de passos de amostragem
            lambda_val: Valor da hora do Caio em USD/hora (se None, usa default_lambda)
            warm_gpus: Dicionário indicando quais GPUs já estão com containers aquecidos {'L4': True}
        
        Returns:
            Dict com a GPU escolhida, estimativas de custo/tempo e razões da decisão.
        """
        # 0. Validação de teto de gastos mensal
        self.budget_manager.enforce_budget()

        # Configura parâmetros
        lambda_hourly = self.default_lambda if lambda_val is None else lambda_val
        warm_map = warm_gpus or {}

        # 1. Filtro RÍGIDO de VRAM
        vram_required = MODEL_VRAM_REQUIREMENTS.get(model.lower(), 16)
        viable_gpus: List[str] = []
        for gpu_name, specs in GPU_SPECS.items():
            if specs["vram_gb"] >= vram_required:
                viable_gpus.append(gpu_name)

        if not viable_gpus:
            raise ValueError(
                f"Nenhuma GPU atende ao requisito de VRAM mínima ({vram_required} GB) para o modelo '{model}'."
            )

        # 2 e 3. Calcular estimativas e scores para todas as GPUs viáveis
        candidates: List[Dict[str, Any]] = []

        for gpu_name in viable_gpus:
            specs = GPU_SPECS[gpu_name]

            # Tenta obter tempo médio histórico do SQLite; se não houver, usa semente
            hist_avg = self.db.get_historical_avg_duration(model, gpu_name, resolution, steps)
            if hist_avg is not None:
                est_duration_s = hist_avg
                is_estimate_from_history = True
            else:
                est_duration_s = get_seed_estimate(model, gpu_name, resolution, steps)
                is_estimate_from_history = False

            # Container quente?
            is_warm = warm_map.get(gpu_name, False)
            cold_start_s = 0.0 if is_warm else specs["default_cold_start_s"]

            # Tempo total = execução estimada + cold start (se houver)
            total_time_s = est_duration_s + cold_start_s
            price_per_sec = specs["price_per_sec"]

            # Custo estimado em USD
            cost_usd = price_per_sec * total_time_s

            # Score = custo(USD) + lambda(USD/hora) * tempo_total(horas)
            time_in_hours = total_time_s / 3600.0
            score = cost_usd + (lambda_hourly * time_in_hours)

            candidates.append(
                {
                    "gpu_name": gpu_name,
                    "modal_gpu_name": specs["modal_gpu_name"],
                    "score": score,
                    "estimated_cost_usd": cost_usd,
                    "estimated_duration_s": est_duration_s,
                    "cold_start_s": cold_start_s,
                    "total_time_s": total_time_s,
                    "is_warm": is_warm,
                    "from_history": is_estimate_from_history,
                }
            )

        # 4. Escolher o menor score (com critério de desempate dando preferência a container quente)
        candidates.sort(key=lambda c: (c["score"], not c["is_warm"], c["estimated_cost_usd"]))
        chosen = candidates[0]

        return {
            "selected_gpu": chosen["gpu_name"],
            "modal_gpu_name": chosen["modal_gpu_name"],
            "estimated_cost_usd": round(chosen["estimated_cost_usd"], 5),
            "estimated_time_s": round(chosen["total_time_s"], 2),
            "execution_time_s": round(chosen["estimated_duration_s"], 2),
            "cold_start_s": chosen["cold_start_s"],
            "is_warm": chosen["is_warm"],
            "score": round(chosen["score"], 5),
            "lambda_used": lambda_hourly,
            "vram_required_gb": vram_required,
            "candidates_evaluated": candidates,
        }
