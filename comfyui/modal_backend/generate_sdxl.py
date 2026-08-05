"""Geração SDXL real no Modal usando o checkpoint do Volume persistente."""

import base64
import io
import time

import modal

MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"
GPU_PRICES_PER_HOUR = {
    "T4": 0.59,
    "L4": 0.80,
    "A10G": 1.10,
    "A100-40GB": 2.10,
    "A100-80GB": 2.50,
    "H100": 3.95,
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


def _generate(prompt: str, seed: int, steps: int, gpu_name: str) -> dict:
    import torch
    from diffusers import StableDiffusionXLPipeline

    checkpoint = f"{MODEL_MOUNT_DIR}/checkpoints/sd_xl_base_1.0.safetensors"
    started = time.perf_counter()
    pipe = StableDiffusionXLPipeline.from_single_file(
        checkpoint,
        config="stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
        use_safetensors=True,
    ).to("cuda")
    generator = torch.Generator(device="cuda").manual_seed(seed)
    result = pipe(prompt=prompt, num_inference_steps=steps, generator=generator).images[0]
    elapsed = time.perf_counter() - started

    buffer = io.BytesIO()
    result.save(buffer, format="PNG")
    return {
        "image_base64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "gpu": gpu_name,
        "duration_seconds": round(elapsed, 3),
        "cost_usd": round(elapsed * GPU_PRICES_PER_HOUR[gpu_name] / 3600.0, 6),
        "seed": seed,
        "steps": steps,
    }


@app.function(image=image, gpu="T4", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_t4(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "T4")


@app.function(image=image, gpu="L4", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_l4(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "L4")


@app.function(image=image, gpu="A10G", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_a10g(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "A10G")


@app.function(image=image, gpu="A100-40GB", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_a100_40gb(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "A100-40GB")


@app.function(image=image, gpu="A100-80GB", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_a100_80gb(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "A100-80GB")


@app.function(image=image, gpu="H100", volumes={MODEL_MOUNT_DIR: volume}, timeout=1800)
def generate_h100(prompt: str, seed: int = 42, steps: int = 20) -> dict:
    return _generate(prompt, seed, steps, "H100")


GENERATORS = {
    "T4": generate_t4,
    "L4": generate_l4,
    "A10G": generate_a10g,
    "A100-40GB": generate_a100_40gb,
    "A100-80GB": generate_a100_80gb,
    "H100": generate_h100,
}


@app.local_entrypoint()
def main(prompt: str = "a cinematic portrait of a Brazilian architect in warm afternoon light", seed: int = 42, steps: int = 20, gpu: str = "L4"):
    import json
    import pathlib

    if gpu not in GENERATORS:
        raise ValueError(f"GPU inválida: {gpu}. Opções: {', '.join(GENERATORS)}")
    result = GENERATORS[gpu].remote(prompt, seed, steps)
    output = pathlib.Path("comfyui/examples/sdxl_modal_result.png")
    output.write_bytes(base64.b64decode(result.pop("image_base64")))
    print(json.dumps({"output": str(output), **result}, indent=2))
