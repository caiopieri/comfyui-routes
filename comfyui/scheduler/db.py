"""
Gerenciador de Banco de Dados SQLite do Scheduler da Casa Amarano.
Registra execuções reais, calcula histórico medido, monitora orçamento mensal e armazena cache.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, Dict, Any, Tuple

DEFAULT_DB_PATH = os.getenv("COMFY_SCHEDULER_DB", os.path.expanduser("~/.comfy_scheduler.db"))


class SchedulerDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Cria as tabelas necessárias se não existirem."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Tabela de histórico de execuções reais
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE NOT NULL,
                    task_type TEXT NOT NULL,
                    model TEXT NOT NULL,
                    gpu TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    steps INTEGER NOT NULL,
                    duration_s REAL NOT NULL,
                    cost_usd REAL NOT NULL,
                    warm_container INTEGER NOT NULL,
                    seed INTEGER,
                    status TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)

            # Tabela de cache por hash de subgrafo
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS job_cache (
                    hash_key TEXT PRIMARY KEY,
                    output_data TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)

            # Index para buscas rápidas no histórico de performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_perf_lookup
                ON executions(model, gpu, resolution, steps)
            """)
            conn.commit()

    def record_execution(
        self,
        job_id: str,
        task_type: str,
        model: str,
        gpu: str,
        resolution: str,
        steps: int,
        duration_s: float,
        cost_usd: float,
        warm_container: bool,
        seed: Optional[int] = None,
        status: str = "SUCCESS",
    ) -> None:
        """Salva a medição de uma execução finalizada no SQLite."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO executions
                (job_id, task_type, model, gpu, resolution, steps, duration_s, cost_usd, warm_container, seed, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    job_id,
                    task_type,
                    model,
                    gpu,
                    resolution,
                    steps,
                    duration_s,
                    cost_usd,
                    1 if warm_container else 0,
                    seed,
                    status,
                    time.time(),
                ),
            )
            conn.commit()

    def get_historical_avg_duration(
        self, model: str, gpu: str, resolution: str = "1024x1024", steps: int = 30
    ) -> Optional[float]:
        """Calcula o tempo médio histórico medido para uma combinação específica de tarefas em execuções bem-sucedidas."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT AVG(duration_s) as avg_duration, COUNT(*) as count
                FROM executions
                WHERE model = ? AND gpu = ? AND resolution = ? AND steps = ? AND status = 'SUCCESS'
            """,
                (model, gpu, resolution, steps),
            )
            row = cursor.fetchone()
            if row and row["count"] and row["count"] >= 1:
                return float(row["avg_duration"])
            return None

    def get_oom_failed_gpus(self, model: str) -> set:
        """GPUs que já deram torch.OutOfMemoryError pra esse modelo — usado
        pra excluir do roteamento sem precisar remedir toda vez."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT gpu FROM executions WHERE model = ? AND status = 'OOM'",
                (model,),
            )
            return {row["gpu"] for row in cursor.fetchall()}

    def get_monthly_cost(self, year: Optional[int] = None, month: Optional[int] = None) -> float:
        """Retorna o custo acumulado em USD no mês especificado (ou no mês atual se omitido)."""
        import datetime
        now = datetime.datetime.now()
        cur_year = year or now.year
        cur_month = month or now.month

        # Timestamp de início e fim do mês
        start_dt = datetime.datetime(cur_year, cur_month, 1, 0, 0, 0)
        if cur_month == 12:
            end_dt = datetime.datetime(cur_year + 1, 1, 1, 0, 0, 0)
        else:
            end_dt = datetime.datetime(cur_year, cur_month + 1, 1, 0, 0, 0)

        start_ts = start_dt.timestamp()
        end_ts = end_dt.timestamp()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT SUM(cost_usd) as total_cost
                FROM executions
                WHERE timestamp >= ? AND timestamp < ? AND status = 'SUCCESS'
            """,
                (start_ts, end_ts),
            )
            row = cursor.fetchone()
            if row and row["total_cost"]:
                return float(row["total_cost"])
            return 0.0

    def get_cached_output(self, hash_key: str) -> Optional[str]:
        """Busca o resultado em cache para um hash de subgrafo."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT output_data FROM job_cache WHERE hash_key = ?", (hash_key,))
            row = cursor.fetchone()
            if row:
                return row["output_data"]
            return None

    def save_cached_output(self, hash_key: str, output_data: str) -> None:
        """Armazena o resultado final no cache."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO job_cache (hash_key, output_data, timestamp) VALUES (?, ?, ?)",
                (hash_key, output_data, time.time()),
            )
            conn.commit()
