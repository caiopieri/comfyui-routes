"""Executor real de workflows ComfyUI em um container Modal."""

import base64
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

import requests

from comfyui.modal_backend.config import GPU_SPECS


class ComfyHeadlessRunner:
    def __init__(self, model_dir: str = "/models", port: int = 8188):
        self.model_dir = Path(model_dir)
        self.output_dir = self.model_dir / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.process = None
        self.comfy_root = None

    def _find_comfy(self) -> Path:
        candidates = [
            Path("/root/comfy/ComfyUI/main.py"),
            Path("/root/ComfyUI/main.py"),
            Path("/opt/ComfyUI/main.py"),
            Path("/ComfyUI/main.py"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise RuntimeError("ComfyUI não foi instalado na imagem Modal")

    def _write_model_paths(self, comfy_root: Path) -> None:
        config = comfy_root / "extra_model_paths.yaml"
        config.write_text(
            "comfyui:\n"
            f"  base_path: {self.model_dir}\n"
            "  checkpoints: checkpoints\n"
            "  configs: configs\n"
            "  vae: vae\n"
            "  loras: loras\n"
            "  diffusion_models: diffusion_models\n"
            "  clip: clip\n"
            "  text_encoders: text_encoders\n"
            "  controlnet: controlnet\n"
            "  upscale_models: upscale_models\n"
            "  latent_upscale_models: latent_upscale_models\n"
            "  embeddings: embeddings\n",
            encoding="utf-8",
        )

    def start(self) -> None:
        if self.process is not None:
            return
        main_py = self._find_comfy()
        self.comfy_root = main_py.parent
        self._write_model_paths(main_py.parent)
        command = [
            "python",
            str(main_py),
            "--listen",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--output-directory",
            str(self.output_dir),
            "--extra-model-paths-config",
            str(main_py.parent / "extra_model_paths.yaml"),
            "--disable-auto-launch",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=str(main_py.parent),
        )
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"ComfyUI encerrou durante a inicialização (code={self.process.returncode})")
            try:
                response = requests.get(f"{self.base_url}/system_stats", timeout=2)
                if response.ok:
                    return
            except requests.RequestException:
                pass
            time.sleep(1)
        raise TimeoutError("ComfyUI headless não respondeu em 180 segundos")

    def _wait_for_history(self, prompt_id: str, timeout_s: int = 1800) -> Dict[str, Any]:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            response = requests.get(f"{self.base_url}/history/{prompt_id}", timeout=10)
            if response.ok:
                history = response.json()
                if prompt_id in history:
                    result = history[prompt_id]
                    if result.get("status", {}).get("status_str") == "error":
                        raise RuntimeError(json.dumps(result, ensure_ascii=False))
                    return result
            time.sleep(1)
        raise TimeoutError(f"Workflow {prompt_id} excedeu {timeout_s}s")

    def _serialize_outputs(self, history: Dict[str, Any]) -> List[Dict[str, Any]]:
        # Em vez de uma lista fixa de chaves conhecidas (images/gifs/videos/
        # audio/3d — descobertas uma a uma toda vez que um tipo novo de nó de
        # saída aparece, ex.: SaveGLB usa "3d", SaveTextNode usa "files"),
        # reconhece pelo FORMATO do item: qualquer lista de dict com
        # "filename" é uma referência a arquivo salvo, seja qual for a
        # chave. Cobre tipos futuros sem precisar de outro patch.
        outputs: List[Dict[str, Any]] = []
        for node_output in history.get("outputs", {}).values():
            for key, items in node_output.items():
                if key == "result" and isinstance(items, list) and items and isinstance(items[0], str):
                    # Save3DAdvanced/SaveGaussianSplat/SavePointCloud usam
                    # PreviewUI3D(Advanced), que foge da convenção de lista
                    # de dict: o arquivo salvo vem como string de caminho
                    # relativo na primeira posição, não um dict "filename".
                    items = [{"filename": items[0], "subfolder": ""}]
                    key = "3d"
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    filename = item.get("filename")
                    subfolder = item.get("subfolder", "")
                    if not filename:
                        continue
                    path = self.output_dir / subfolder / filename
                    if not path.exists():
                        raise FileNotFoundError(f"Saída do ComfyUI não encontrada: {path}")
                    outputs.append({
                        "type": key[:-1] if key.endswith("s") else key,
                        "filename": filename,
                        "subfolder": subfolder,
                        "format": path.suffix.lstrip("."),
                        "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                    })
        if not outputs:
            raise RuntimeError("Workflow terminou sem arquivos de saída")
        return outputs

    def execute_workflow(
        self,
        workflow: Dict[str, Any],
        gpu_type: str = "L4",
        is_warm: bool = False,
        timeout_s: int = 1800,
        input_files: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        if gpu_type not in GPU_SPECS:
            raise ValueError(f"GPU não catalogada: {gpu_type}")
        started = time.perf_counter()
        self.start()
        if input_files:
            input_dir = self.comfy_root / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            for filename, data_base64 in input_files.items():
                safe_name = Path(filename).name
                (input_dir / safe_name).write_bytes(base64.b64decode(data_base64))
        response = requests.post(
            f"{self.base_url}/prompt",
            json={"prompt": workflow, "client_id": str(uuid.uuid4())},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"ComfyUI remoto recusou o workflow ({response.status_code}): {response.text}"
            )
        submitted = response.json()
        if submitted.get("node_errors"):
            raise ValueError(json.dumps(submitted["node_errors"], ensure_ascii=False))
        prompt_id = submitted.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI não retornou prompt_id: {submitted}")
        history = self._wait_for_history(prompt_id, timeout_s)
        outputs = self._serialize_outputs(history)
        duration_s = time.perf_counter() - started
        specs = GPU_SPECS[gpu_type]
        cold_start_s = 0.0 if is_warm else specs["default_cold_start_s"]
        billed_s = duration_s + cold_start_s
        return {
            "job_id": prompt_id,
            "status": "SUCCESS",
            "outputs": outputs,
            "metrics": {
                "gpu": gpu_type,
                "duration_s": round(duration_s, 3),
                "cold_start_s": cold_start_s,
                "total_billed_time_s": round(billed_s, 3),
                "actual_cost_usd": round(billed_s * specs["price_per_sec"], 6),
                "is_warm": is_warm,
            },
        }

    def execute_subgraph(self, subgraph_json: Dict[str, Any], gpu_type: str = "L4", is_warm: bool = False) -> Dict[str, Any]:
        workflow = subgraph_json.get("workflow", subgraph_json)
        if not isinstance(workflow, dict) or not workflow:
            raise ValueError("Workflow ComfyUI vazio ou inválido")
        return self.execute_workflow(workflow, gpu_type=gpu_type, is_warm=is_warm)
