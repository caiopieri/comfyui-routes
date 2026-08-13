"""
Testes Unitários Automatizados do Scheduler de GPU da Casa Amarano.
Valida filtro rígido de VRAM, calculador de score, histórico SQLite e teto de gastos.
"""

import unittest
import tempfile
import os
import time

from comfyui.scheduler.db import SchedulerDB
from comfyui.scheduler.budget import BudgetManager, BudgetExceededException
from comfyui.scheduler.router import GPURouter
from comfyui.scheduler.batch import BatchScheduler
from comfyui.scheduler.seed_data import get_seed_estimate
from comfyui.modal_backend.config import GPU_SPECS, MODEL_PROFILES


class TestGPUScheduler(unittest.TestCase):

    def setUp(self):
        # Cria banco de dados temporário isolado para testes
        self.temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db_file.name
        self.temp_db_file.close()

        self.db = SchedulerDB(db_path=self.db_path)
        self.budget_manager = BudgetManager(db=self.db, budget_cap_usd=50.0)
        self.router = GPURouter(db=self.db, budget_manager=self.budget_manager, default_lambda=15.0)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_vram_rigid_filter(self):
        """Wan 2.2 14B exige 24GB VRAM e NUNCA deve escolher T4 (16GB)."""
        decision = self.router.route_job(model="wan_2_2_14b", steps=30)
        selected = decision["selected_gpu"]
        self.assertNotEqual(selected, "T4", "T4 não possui VRAM suficiente para Wan 2.2 14B!")
        self.assertIn(selected, ["A100-80GB", "H100"])

    def test_catalog_vram_matrix(self):
        """Cada perfil só oferece GPUs com a folga mínima declarada."""
        for model, profile in MODEL_PROFILES.items():
            required = profile["vram_min_gb"]
            decision = self.router.route_job(model=model, steps=4)
            viable = {c["gpu_name"] for c in decision["candidates_evaluated"]}
            expected = {name for name, specs in GPU_SPECS.items() if specs["vram_gb"] >= required}
            self.assertEqual(viable, expected, model)

    def test_latest_profiles_gpu_boundaries(self):
        """Perfis conhecidos têm limites verificáveis, sem esconder OOM atrás de L4."""
        self.assertEqual(
            {c["gpu_name"] for c in self.router.route_job("flux2_klein_4b")["candidates_evaluated"]},
            set(GPU_SPECS),
        )
        self.assertEqual(
            {c["gpu_name"] for c in self.router.route_job("wan_2_2_14b")["candidates_evaluated"]},
            {"A100-80GB", "H100"},
        )

    def test_model_alias_is_canonicalized(self):
        """Aliases comuns não caem silenciosamente no fallback de 16 GB."""
        decision = self.router.route_job("hunyuanvideo-1.5")
        self.assertEqual(decision["vram_required_gb"], 16)

    def test_warm_container_preference(self):
        """Se L4 estiver aquecida, cold_start deve ser 0 e alterar o score."""
        decision_cold = self.router.route_job(model="sdxl", steps=30, warm_gpus={"L4": False})
        decision_warm = self.router.route_job(model="sdxl", steps=30, warm_gpus={"L4": True})

        # Ao estar aquecida, a GPU L4 deve ter 0s de cold start
        l4_warm_cand = [c for c in decision_warm["candidates_evaluated"] if c["gpu_name"] == "L4"][0]
        self.assertEqual(l4_warm_cand["cold_start_s"], 0.0)

    def test_historical_update(self):
        """Histórico real medido deve se sobrepor à semente após execução gravada."""
        model = "sdxl"
        gpu = "L4"
        resolution = "1024x1024"
        steps = 30

        # Grava 3 execuções reais com tempo médio de 5.0 segundos no SQLite
        for i in range(3):
            self.db.record_execution(
                job_id=f"test-hist-{i}",
                task_type="txt2img",
                model=model,
                gpu=gpu,
                resolution=resolution,
                steps=steps,
                duration_s=5.0,
                cost_usd=0.001,
                warm_container=True,
                status="SUCCESS",
            )

        avg_dur = self.db.get_historical_avg_duration(model, gpu, resolution, steps)
        self.assertIsNotNone(avg_dur)
        self.assertAlmostEqual(avg_dur, 5.0, places=2)

    def test_budget_cap_enforcement(self):
        """Atingir o teto mensal deve bloquear novas execuções com BudgetExceededException."""
        # Registra um gasto de $55.0 USD (acima do teto de $50.0)
        self.db.record_execution(
            job_id="expensive-job",
            task_type="txt2video",
            model="wan_2_2_14b",
            gpu="H100",
            resolution="1280x720",
            steps=50,
            duration_s=100.0,
            cost_usd=55.0,
            warm_container=False,
            status="SUCCESS",
        )

        with self.assertRaises(BudgetExceededException):
            self.router.route_job(model="sdxl", steps=30)

    def test_vram_override_takes_priority_over_catalog(self):
        """vram_override_gb (estimativa dinâmica por tamanho) tem prioridade
        sobre MODEL_VRAM_REQUIREMENTS — é assim que modelo sem catálogo
        (workflow_resolver.py) escolhe GPU certa sem cadastro manual."""
        decision = self.router.route_job(model="auto_deadbeef1234", steps=20, vram_override_gb=48)
        viable = {c["gpu_name"] for c in decision["candidates_evaluated"]}
        self.assertEqual(viable, {"A100-80GB", "H100"})

    def test_oom_failed_gpu_is_excluded_from_next_route(self):
        """GPU que já deu OutOfMemoryError nesse modelo não deve ser
        oferecida de novo — é o que permite o retry automático em
        dispatch_workflow.py escalar sozinho sem repetir o mesmo erro."""
        model = "auto_deadbeef1234"
        self.db.record_execution(
            job_id="oom-test-1",
            task_type="workflow",
            model=model,
            gpu="A100-80GB",
            resolution="1024x1024",
            steps=20,
            duration_s=12.0,
            cost_usd=0.01,
            warm_container=False,
            status="OOM",
        )
        decision = self.router.route_job(model=model, steps=20, vram_override_gb=48)
        viable = {c["gpu_name"] for c in decision["candidates_evaluated"]}
        self.assertEqual(viable, {"H100"})

    def test_all_gpus_oom_raises_clear_error(self):
        """Se até a maior GPU do catálogo já deu OOM, erro tem que deixar
        claro o motivo (não confundir com "VRAM insuficiente")."""
        model = "auto_deadbeef1234"
        for gpu in ("A100-80GB", "H100"):
            self.db.record_execution(
                job_id=f"oom-test-{gpu}",
                task_type="workflow",
                model=model,
                gpu=gpu,
                resolution="1024x1024",
                steps=20,
                duration_s=12.0,
                cost_usd=0.01,
                warm_container=False,
                status="OOM",
            )
        with self.assertRaisesRegex(ValueError, "OutOfMemoryError"):
            self.router.route_job(model=model, steps=20, vram_override_gb=48)

    def test_batch_scheduler(self):
        """Testa o agrupamento em lote (BatchScheduler)."""
        batch_sched = BatchScheduler()
        batch_sched.enqueue_job("job1", "sdxl", "1024x1024", 30, {"prompt": "A cat"})
        batch_sched.enqueue_job("job2", "sdxl", "1024x1024", 30, {"prompt": "A dog"})

        pending = batch_sched.get_pending_batches()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
