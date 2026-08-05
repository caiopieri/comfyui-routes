import tempfile
import unittest

from comfyui.dispatch.dispatch_plan import build_dispatch_plan
from comfyui.scheduler.budget import BudgetManager
from comfyui.scheduler.db import SchedulerDB
from comfyui.scheduler.router import GPURouter


class TestDispatchPlan(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.file.close()
        self.db = SchedulerDB(self.file.name)
        self.router = GPURouter(self.db, BudgetManager(self.db, 50), default_lambda=0)

    def tearDown(self):
        import os
        os.unlink(self.file.name)

    def test_modal_plan_contains_route(self):
        plan = build_dispatch_plan(
            {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_t2v_14B.safetensors"}}},
            self.router,
            resolution="1280x720",
            steps=30,
            lambda_val=0,
            local_model_roots=["/tmp/no-models"],
        )
        self.assertEqual(plan["target"], "modal")
        self.assertEqual(plan["route"]["selected_gpu"], "A100-80GB")

    def test_local_plan_does_not_pick_gpu(self):
        with tempfile.TemporaryDirectory() as directory:
            import pathlib
            pathlib.Path(directory, "sd_xl_base.safetensors").touch()
            plan = build_dispatch_plan(
                {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}}},
                self.router,
                local_model_roots=[directory],
            )
        self.assertEqual(plan["target"], "local")
        self.assertIsNone(plan["route"])


if __name__ == "__main__":
    unittest.main()
