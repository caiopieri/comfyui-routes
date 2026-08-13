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

    def test_ltx_23_workflow_uses_ltx_profile(self):
        workflow = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "ltx-2.3-22b-dev-fp8.safetensors"},
            }
        }
        result = resolve_workflow(workflow, ["/tmp/empty-models"])
        self.assertEqual(result.model, "ltx_video")
        self.assertEqual(result.vram_required_gb, 64)
        self.assertTrue(result.needs_modal)


    def test_unknown_model_estimates_vram_from_metadata_size(self):
        """Modelo sem token cadastrado, mas com properties.models embutida
        (biblioteca oficial de templates) estima VRAM pelo tamanho real dos
        pesos em vez de cair no default "sdxl" — é o que evita precisar
        cadastrar cada modelo novo manualmente."""
        workflow = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "modelo_desconhecido_xyz.safetensors"},
            }
        }
        # 30GB total de peso já-conhecido (sem precisar de rede: size_bytes
        # informado direto) -> 30*1.6=48GB -> arredonda pro tier de 80GB.
        metadata = [
            {"name": "modelo_desconhecido_xyz.safetensors", "url": "https://exemplo.test/a.safetensors", "size_bytes": 30 * 1024**3},
        ]
        result = resolve_workflow(workflow, ["/tmp/empty-models"], models_metadata=metadata, fetch_sizes=False)
        self.assertTrue(result.model.startswith("auto_"))
        self.assertEqual(result.vram_required_gb, 80)
        self.assertTrue(result.needs_modal)

    def test_unknown_model_without_metadata_falls_back_to_sdxl(self):
        """Sem token E sem metadata (workflow da comunidade sem a
        informação embutida), mantém o chute conservador anterior — não dá
        pra estimar por tamanho sem nenhuma pista."""
        workflow = {
            "1": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": "modelo_totalmente_desconhecido.safetensors"},
            }
        }
        result = resolve_workflow(workflow, ["/tmp/empty-models"], fetch_sizes=False)
        self.assertEqual(result.model, "sdxl")

    def test_synthetic_model_id_is_stable_across_calls(self):
        """Mesmos arquivos referenciados -> mesmo id sintético sempre — é
        assim que o aprendizado de OOM no scheduler DB reconhece "já vi
        esse modelo antes" sem cadastro manual."""
        workflow = {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "modelo_x.safetensors"}},
        }
        metadata = [{"name": "modelo_x.safetensors", "url": "https://exemplo.test/x.safetensors", "size_bytes": 10 * 1024**3}]
        r1 = resolve_workflow(workflow, ["/tmp/empty-models"], models_metadata=metadata, fetch_sizes=False)
        r2 = resolve_workflow(workflow, ["/tmp/empty-models"], models_metadata=metadata, fetch_sizes=False)
        self.assertEqual(r1.model, r2.model)


if __name__ == "__main__":
    unittest.main()
