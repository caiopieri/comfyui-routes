"""
EXECUTOR_REVISION = "2026-08-06-warm-workflow-v3"
Definição do App Modal para ComfyUI Serverless da Casa Amarano.
Monta o Volume persistente de modelos e disponibiliza uma classe de worker
por GPU, cada uma com @modal.enter() subindo o ComfyUI headless uma única
vez por container — chamadas seguintes no mesmo container quente reaproveitam
o processo e os checkpoints já carregados em VRAM.
"""

import modal
from comfyui.modal_backend.config import (
    GPU_SPECS,
    MODEL_VOLUME_NAME,
    MODEL_MOUNT_DIR,
    DEFAULT_CONTAINER_IDLE_TIMEOUT,
)

# 1. Definição do App no Modal
app = modal.App("casa-amarano-comfyui")

# 2. Volume Persistente para Modelos (Checkpoints, LoRAs, VAEs, Outputs)
models_volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)

# 3. Definição da Imagem do Container com dependências do ComfyUI e PyTorch
comfy_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "wget")
    .pip_install("torch", "torchvision", "torchaudio", extra_options="--index-url https://download.pytorch.org/whl/cu121")
    .pip_install("comfy-cli", "requests", "pillow", "websocket-client")
    .run_commands("comfy --skip-prompt install --nvidia")
)


class _ComfyWorkflowWorker:
    gpu_type: str = "L4"

    @modal.enter()
    def setup(self):
        from comfyui.modal_backend.comfy_runner import ComfyHeadlessRunner

        self.runner = ComfyHeadlessRunner(model_dir=MODEL_MOUNT_DIR)
        self.calls = 0

    @modal.method()
    def run(self, workflow: dict, input_files: dict | None = None) -> dict:
        is_warm = self.calls > 0
        self.calls += 1
        return self.runner.execute_workflow(
            workflow, gpu_type=self.gpu_type, is_warm=is_warm, input_files=input_files
        )


# Modal exige que classes @app.cls estejam em escopo global — uma fábrica
# dentro de função não serializa. Uma classe explícita por GPU catalogada.
@app.cls(image=comfy_image, gpu=GPU_SPECS["T4"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerT4(_ComfyWorkflowWorker):
    gpu_type = "T4"


@app.cls(image=comfy_image, gpu=GPU_SPECS["L4"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerL4(_ComfyWorkflowWorker):
    gpu_type = "L4"


@app.cls(image=comfy_image, gpu=GPU_SPECS["A10G"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerA10G(_ComfyWorkflowWorker):
    gpu_type = "A10G"


@app.cls(image=comfy_image, gpu=GPU_SPECS["A100-40GB"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerA10040GB(_ComfyWorkflowWorker):
    gpu_type = "A100-40GB"


@app.cls(image=comfy_image, gpu=GPU_SPECS["A100-80GB"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerA10080GB(_ComfyWorkflowWorker):
    gpu_type = "A100-80GB"


@app.cls(image=comfy_image, gpu=GPU_SPECS["H100"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: models_volume}, scaledown_window=DEFAULT_CONTAINER_IDLE_TIMEOUT, timeout=1800)
class ComfyWorkflowWorkerH100(_ComfyWorkflowWorker):
    gpu_type = "H100"


WORKFLOW_WORKERS = {
    "T4": ComfyWorkflowWorkerT4,
    "L4": ComfyWorkflowWorkerL4,
    "A10G": ComfyWorkflowWorkerA10G,
    "A100-40GB": ComfyWorkflowWorkerA10040GB,
    "A100-80GB": ComfyWorkflowWorkerA10080GB,
    "H100": ComfyWorkflowWorkerH100,
}


@app.function(
    image=comfy_image,
    volumes={MODEL_MOUNT_DIR: models_volume},
)
def check_status() -> dict:
    """Função de diagnóstico para verificar status do Volume e da aplicação."""
    import os
    items = os.listdir(MODEL_MOUNT_DIR) if os.path.exists(MODEL_MOUNT_DIR) else []
    return {
        "status": "online",
        "volume_mount": MODEL_MOUNT_DIR,
        "volume_contents": items,
    }
