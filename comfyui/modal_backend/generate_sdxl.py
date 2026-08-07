"""Geração SDXL real no Modal usando o checkpoint do Volume persistente.

Autocontido de propósito: este script é montado sozinho dentro do container
Modal (flat, em /root/generate_sdxl.py), sem o resto do pacote `comfyui`
disponível remotamente. Importar de comfyui.modal_backend.config aqui
crash-loopa o worker com ModuleNotFoundError. Preços/specs duplicados de
config.py; se mudar lá, replicar aqui.

Uma classe por GPU (@app.cls) com @modal.enter() carregando o pipeline
uma única vez por container. Chamadas seguintes no mesmo container quente
reaproveitam o pipeline já em VRAM — sem isso, cada chamada recarregava o
checkpoint de 6.5GB do zero, mesmo com o container do Modal já quente.
"""

import base64
import io
import time

import modal

MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"
CONTAINER_IDLE_TIMEOUT = 300  # espelha DEFAULT_CONTAINER_IDLE_TIMEOUT em config.py
GPU_SPECS = {
    "T4": {"modal_gpu_name": "t4", "price_per_sec": 0.59 / 3600.0},
    "L4": {"modal_gpu_name": "l4", "price_per_sec": 0.80 / 3600.0},
    "A10G": {"modal_gpu_name": "a10g", "price_per_sec": 1.10 / 3600.0},
    "A100-40GB": {"modal_gpu_name": "a100-40gb", "price_per_sec": 2.10 / 3600.0},
    "A100-80GB": {"modal_gpu_name": "a100-80gb", "price_per_sec": 2.50 / 3600.0},
    "H100": {"modal_gpu_name": "h100", "price_per_sec": 3.95 / 3600.0},
}

app = modal.App("casa-amarano-sdxl")
volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=False)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch",
        "diffusers",
        "transformers",
        "accelerate",
        "safetensors",
        "Pillow",
    )
)


class _SDXLWorker:
    gpu_name: str = "L4"

    @modal.enter()
    def setup(self):
        import torch
        from diffusers import StableDiffusionXLPipeline

        checkpoint = f"{MODEL_MOUNT_DIR}/checkpoints/sd_xl_base_1.0.safetensors"
        started = time.perf_counter()
        self.pipe = StableDiffusionXLPipeline.from_single_file(
            checkpoint,
            config="stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float16,
            use_safetensors=True,
        ).to("cuda")
        self.load_time_s = time.perf_counter() - started
        self.calls = 0

    @modal.method()
    def generate(self, prompt: str, seed: int = 42, steps: int = 20) -> dict:
        import torch

        started = time.perf_counter()
        generator = torch.Generator(device="cuda").manual_seed(seed)
        result = self.pipe(prompt=prompt, num_inference_steps=steps, generator=generator).images[0]
        inference_s = time.perf_counter() - started

        is_warm = self.calls > 0
        self.calls += 1
        billed_s = inference_s if is_warm else inference_s + self.load_time_s

        buffer = io.BytesIO()
        result.save(buffer, format="PNG")
        price_per_sec = GPU_SPECS[self.gpu_name]["price_per_sec"]
        return {
            "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            "gpu": self.gpu_name,
            "duration_seconds": round(billed_s, 3),
            "inference_seconds": round(inference_s, 3),
            "load_seconds": round(self.load_time_s, 3) if not is_warm else 0.0,
            "cost_usd": round(billed_s * price_per_sec, 6),
            "is_warm": is_warm,
            "seed": seed,
            "steps": steps,
        }


# Modal exige que classes @app.cls estejam em escopo global (precisa importar
# por nome qualificado) — uma fábrica dentro de função não serializa. Por isso
# uma classe explícita por GPU, igual ao padrão já usado no resto do arquivo.
@app.cls(image=image, gpu=GPU_SPECS["T4"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerT4(_SDXLWorker):
    gpu_name = "T4"


@app.cls(image=image, gpu=GPU_SPECS["L4"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerL4(_SDXLWorker):
    gpu_name = "L4"


@app.cls(image=image, gpu=GPU_SPECS["A10G"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerA10G(_SDXLWorker):
    gpu_name = "A10G"


@app.cls(image=image, gpu=GPU_SPECS["A100-40GB"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerA10040GB(_SDXLWorker):
    gpu_name = "A100-40GB"


@app.cls(image=image, gpu=GPU_SPECS["A100-80GB"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerA10080GB(_SDXLWorker):
    gpu_name = "A100-80GB"


@app.cls(image=image, gpu=GPU_SPECS["H100"]["modal_gpu_name"], volumes={MODEL_MOUNT_DIR: volume}, scaledown_window=CONTAINER_IDLE_TIMEOUT, timeout=1800)
class SDXLWorkerH100(_SDXLWorker):
    gpu_name = "H100"


GENERATORS = {
    "T4": SDXLWorkerT4,
    "L4": SDXLWorkerL4,
    "A10G": SDXLWorkerA10G,
    "A100-40GB": SDXLWorkerA10040GB,
    "A100-80GB": SDXLWorkerA10080GB,
    "H100": SDXLWorkerH100,
}


@app.local_entrypoint()
def main(prompt: str = "a cinematic portrait of a Brazilian architect in warm afternoon light", seed: int = 42, steps: int = 20, gpu: str = "L4"):
    import json
    import pathlib

    if gpu not in GENERATORS:
        raise ValueError(f"GPU inválida: {gpu}. Opções: {', '.join(GENERATORS)}")
    # `modal run` cria um app efêmero: se chamássemos GENERATORS[gpu]() direto,
    # o container seria desligado junto com o app quando este processo CLI
    # terminasse, e a próxima chamada recomeçaria fria — mesmo com o container
    # ainda dentro do scaledown_window. Cls.from_name busca a classe no app JÁ
    # DEPLOYADO (`modal deploy generate_sdxl.py`), cujos containers persistem
    # entre invocações independentes, o que é o que de fato reaproveita o
    # container quente.
    worker_cls = modal.Cls.from_name("casa-amarano-sdxl", f"SDXLWorker{gpu.replace('-', '')}")
    result = worker_cls().generate.remote(prompt, seed, steps)
    output = pathlib.Path("comfyui/examples/sdxl_modal_result.png")
    output.write_bytes(base64.b64decode(result.pop("image_base64")))
    print(json.dumps({"output": str(output), **result}, indent=2))
