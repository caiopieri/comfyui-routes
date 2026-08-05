"""
Gerenciador de Teto de Gastos (Budget Cap) do Scheduler da Casa Amarano.
Verifica se o limite mensal foi atingido antes de disparar novas GPUs no Modal.
"""

from typing import Tuple
from comfyui.modal_backend.config import DEFAULT_MONTHLY_BUDGET_CAP
from comfyui.scheduler.db import SchedulerDB


class BudgetExceededException(Exception):
    """Exceção lançada quando o teto de gastos mensal foi excedido."""
    pass


class BudgetManager:
    def __init__(self, db: SchedulerDB, budget_cap_usd: float = DEFAULT_MONTHLY_BUDGET_CAP):
        self.db = db
        self.budget_cap_usd = budget_cap_usd

    def check_budget_ok(self) -> Tuple[bool, float, float]:
        """
        Verifica o gasto atual do mês.
        Retorna (is_ok, gasto_atual_usd, teto_usd).
        """
        current_spent = self.db.get_monthly_cost()
        is_ok = current_spent < self.budget_cap_usd
        return is_ok, current_spent, self.budget_cap_usd

    def enforce_budget(self) -> None:
        """
        Valida o teto mensal. Se ultrapassado, lança exceção bloqueando o disparo.
        """
        is_ok, current_spent, cap = self.check_budget_ok()
        if not is_ok:
            raise BudgetExceededException(
                f"[BLOQUEIO DE SEGURANÇA] Teto de gastos mensal do Modal foi atingido! "
                f"Gasto Atual: ${current_spent:.2f} USD | Teto Máximo: ${cap:.2f} USD. "
                f"Novas execuções de GPU estão suspensas até o próximo mês ou reajuste de COMFY_MONTHLY_BUDGET_CAP."
            )
