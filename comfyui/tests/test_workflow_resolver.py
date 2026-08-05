import tempfile
import unittest
from pathlib import Path

from comfyui.dispatch.workflow_resolver import resolve_workflow


class TestWorkflowResolver(unittest.TestCase):
    def test_missing_wan_checkpoint_requires_modal(self):
        workflow = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "wan2.2_t2v_14B_fp16.safetensors"},
            }
        }
        result = resolve_workflow(workflow, ["/tmp/empty-models"])
        self.assertEqual(result.model, "wan_2_2_14b")
        self.assertTrue(result.needs_modal)
        self.assertEqual(result.vram_required_gb, 80)

    def test_all_required_files_local_stays_local(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "sd_xl_base_1.0.safetensors").touch()
            workflow = {
                "1": {
                    "class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
                }
            }
            result = resolve_workflow(workflow, [directory])
            self.assertEqual(result.model, "sdxl")
            self.assertFalse(result.needs_modal)
            self.assertEqual(result.missing_files, [])

    def test_workflow_without_explicit_checkpoint_defaults_to_sdxl(self):
        result = resolve_workflow({"1": {"class_type": "CLIPTextEncode", "inputs": {}}})
        self.assertEqual(result.model, "sdxl")
        self.assertFalse(result.needs_modal)


if __name__ == "__main__":
    unittest.main()
