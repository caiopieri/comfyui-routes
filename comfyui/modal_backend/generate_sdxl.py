"""Geração SDXL real no Modal usando o checkpoint do Volume persistente."""

import base64
import io
import time

import modal

MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"
GPU_NAME = "L4"
GPU_PRICE_PER_SECOND = 0.80 / 3600.0

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


@app.function(
    image=image,
    gpu="L4",
    volumes={MODEL_MOUNT_DIR: volume},
    timeout=1800,
)
def generate(prompt: str, seed: int = 42, steps: int = 20) -> dict:
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
        "gpu": GPU_NAME,
        "duration_seconds": round(elapsed, 3),
        "cost_usd": round(elapsed * GPU_PRICE_PER_SECOND, 6),
        "seed": seed,
        "steps": steps,
    }


@app.local_entrypoint()
def main(prompt: str = "a cinematic portrait of a Brazilian architect in warm afternoon light", seed: int = 42, steps: int = 20):
    import json
    import pathlib

    result = generate.remote(prompt, seed, steps)
    output = pathlib.Path("comfyui/examples/sdxl_modal_result.png")
    output.write_bytes(base64.b64decode(result.pop("image_base64")))
    print(json.dumps({"output": str(output), **result}, indent=2))
