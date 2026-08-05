"""
Definição do App Modal para ComfyUI Serverless da Casa Amarano.
Monta o Volume persistente de modelos, implementa @enter() para pré-carregamento,
configura container_idle_timeout ~5min e disponibiliza funções de inferência.
"""

import modal
from comfyui.modal_backend.config import (
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
    .pip_install("torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu121")
    .pip_install("comfy-cli", "requests", "pillow", "websocket-client", "sqlite3")
    .run_commands("comfy --skip-prompt install --nvidia || true")
)


@app.cls(
    image=comfy_image,
    volumes={MODEL_MOUNT_DIR: models_volume},
    container_idle_timeout=DEFAULT_CONTAINER_IDLE_TIMEOUT,  # 5 minutos aquecido para iteração barata
    timeout=600,
)
class ComfyWorker:
    @modal.enter()
    def setup(self):
        """
        Executado UMA ÚNICA VEZ ao subir o container da GPU.
        Carrega modelos do Volume persistente para a VRAM da GPU.
        """
        import os
        print(f"[Modal Worker] Container inicializado! Carregando modelos de {MODEL_MOUNT_DIR}...")
        os.makedirs(os.path.join(MODEL_MOUNT_DIR, "checkpoints"), exist_ok=True)
        os.makedirs(os.path.join(MODEL_MOUNT_DIR, "outputs"), exist_ok=True)
        # Inicialização do runner headless
        from comfyui.modal_backend.comfy_runner import ComfyHeadlessRunner
        self.runner = ComfyHeadlessRunner(model_dir=MODEL_MOUNT_DIR)
        print("[Modal Worker] Modelos pré-carregados na VRAM com sucesso.")

    @modal.method()
    def run_subgraph(self, subgraph_json: dict, gpu_type: str = "L4") -> dict:
        """
        Executa um subgrafo enviado pelo nó local do ComfyUI.
        """
        print(f"[Modal Worker] Recebido subgrafo para execução na GPU {gpu_type}.")
        result = self.runner.execute_subgraph(
            subgraph_json=subgraph_json,
            gpu_type=gpu_type,
            is_warm=True,
        )
        return result


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
