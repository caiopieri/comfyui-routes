"""
EXECUTOR_REVISION = "2026-08-11-force-redeploy-v4"
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
#
# add_local_python_source é explícito de propósito: comfy_runner.py só é
# importado dentro de setup() (@modal.enter()), em runtime dentro do
# container — o auto-mount do Modal não detecta esse import porque ele não
# roda no momento do `modal deploy comfyui/modal_backend/app.py` (só executa
# quando o método é chamado remotamente). Sem isso, o deploy direto de
# app.py nunca inclui o pacote `comfyui` (confirmado: nenhum mount
# "PythonPackage:comfyui" aparece no log de deploy), e o worker crash-loopa
# silenciosamente com ModuleNotFoundError a cada tentativa — sem erro visível
# no client local, que fica parado esperando indefinidamente.
comfy_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "wget")
    # cu121 trava o torch numa versão velha demais (2.5.1) — comfy-kitchen
    # (dependência do core, ver abaixo) usa torch.library.custom_op com
    # generics nativos (list[int]) que o infer_schema só suporta a partir
    # de versões mais novas. cu124 tem builds recentes o bastante.
    # Trio sem pin dá ResolutionImpossible (conflito de nvidia-cudnn-cu12
    # entre candidatos) — versões exatas compatíveis entre si por release
    # oficial do PyTorch. torch==2.6.0 pede nvidia-cudnn-cu12==9.1.0.70, que
    # sumiu do índice da NVIDIA (pulado direto de 9.0.0.312 pra 9.1.1.17) —
    # 2.7.0 pede 9.5.1.17, que ainda existe. cu124 só vai até 2.6.0; 2.7.0+
    # está só no índice cu128.
    .pip_install("torch==2.7.0", "torchvision==0.22.0", "torchaudio==2.7.0", extra_options="--index-url https://download.pytorch.org/whl/cu128")
    .pip_install("comfy-cli", "requests", "pillow", "websocket-client")
    .run_commands("comfy --skip-prompt install --nvidia")
    # comfy-cli instala uma tag fixa do ComfyUI, que fica atrás da versão
    # que tem os nós que os templates oficiais mais novos precisam (ex.:
    # LTXVDualCFGGuider, em comfy_extras/nodes_lt.py, usado pelo template
    # LTX-2.5) — sem isso o /prompt remoto recusa com "missing_node_type"
    # mesmo com os pesos certos no Volume. v0.32.0 é a primeira tag oficial
    # que já inclui esse nó (confirmado por inspeção do histórico do repo)
    # — usar a tag exata, e não master, evita puxar código ainda não
    # testado/lançado cujas dependências (torch, comfy-kitchen) podem ter
    # mudado sem aviso.
    .run_commands(
        "cd /root/comfy/ComfyUI "
        "&& git fetch --depth 1 origin tag v0.32.0 "
        "&& git checkout v0.32.0 "
        # Reinstala a partir do requirements.txt DESSA tag (não o que o
        # comfy-cli tinha instalado pra tag antiga) — evita reinstalar
        # dependências peça por peça e ficar perseguindo incompatibilidades
        # em cascata (torch <-> comfy-kitchen <-> kornia).
        "&& pip install -r requirements.txt"
    )
    # requirements.txt da v0.32.0 pede kornia>=0.7.1, e sem pin específico
    # o pip pega a mais nova (0.8.x), que removeu o re-export `pad` de
    # kornia.geometry.transform.pyramid usado pelo nó customizado abaixo
    # (ImportError silencioso, nó some do ComfyUI). 0.7.4 satisfaz o
    # >=0.7.1 do core e ainda tem o `pad`.
    .run_commands("pip install 'kornia==0.7.4'")
    # Nós customizados adicionais que o template LTX-2.5 também usa (ex.:
    # prompt enhancer, blending) e que não fazem parte do core.
    .run_commands(
        "cd /root/comfy/ComfyUI/custom_nodes "
        "&& git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo.git "
        "&& (pip install -r ComfyUI-LTXVideo/requirements.txt || true) "
        "&& pip install 'kornia==0.7.4'"
    )
    .add_local_python_source("comfyui")
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
