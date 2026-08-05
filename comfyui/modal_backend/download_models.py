"""
Baixa modelos direto do Hugging Face para o Volume persistente do Modal.

Muito mais rápido que baixar na máquina local e fazer upload: o download
acontece na rede do datacenter e o arquivo nunca passa pela sua internet.

Uso:
    modal run comfyui/modal_backend/download_models.py --preset sdxl
    modal run comfyui/modal_backend/download_models.py --preset flux-schnell
    modal run comfyui/modal_backend/download_models.py --repo <repo> --arquivo <file> --destino checkpoints

Listar o que já está no volume:
    modal volume ls comfyui-models-vol /checkpoints
"""

import modal

MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"

app = modal.App("casa-amarano-download-models")

volume = modal.Volume.from_name(MODEL_VOLUME_NAME, create_if_missing=True)

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "huggingface_hub[hf_transfer]==0.26.2"
)

# Presets prontos. Comece pelo sdxl: é leve, rápido e ótimo para aprender.
PRESETS = {
    "sdxl": [
        {
            "repo": "stabilityai/stable-diffusion-xl-base-1.0",
            "arquivo": "sd_xl_base_1.0.safetensors",
            "destino": "checkpoints",
        },
        {
            "repo": "madebyollin/sdxl-vae-fp16-fix",
            "arquivo": "sdxl_vae.safetensors",
            "destino": "vae",
        },
    ],
    "flux-schnell": [
        {
            "repo": "black-forest-labs/FLUX.1-schnell",
            "arquivo": "flux1-schnell.safetensors",
            "destino": "checkpoints",
        },
    ],
}


@app.function(
    image=image,
    volumes={MODEL_MOUNT_DIR: volume},
    timeout=60 * 60,
    # Repositórios privados/gated (ex.: FLUX) exigem token do Hugging Face.
    # Crie o secret uma vez com:
    #   modal secret create huggingface HF_TOKEN=hf_xxxxx
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def baixar(repo: str, arquivo: str, destino: str = "checkpoints"):
    """Baixa um arquivo do Hugging Face direto para o volume."""
    import os

    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    from huggingface_hub import hf_hub_download

    pasta = os.path.join(MODEL_MOUNT_DIR, destino)
    os.makedirs(pasta, exist_ok=True)

    destino_final = os.path.join(pasta, arquivo)
    if os.path.exists(destino_final):
        tamanho = os.path.getsize(destino_final) / (1024**3)
        print(f"[pular] {arquivo} já existe ({tamanho:.1f} GB)")
        return destino_final

    print(f"[baixando] {repo} :: {arquivo} -> {pasta}")
    caminho = hf_hub_download(
        repo_id=repo,
        filename=arquivo,
        local_dir=pasta,
        token=os.environ.get("HF_TOKEN"),
    )

    volume.commit()
    tamanho = os.path.getsize(caminho) / (1024**3)
    print(f"[ok] {arquivo} — {tamanho:.1f} GB gravado no volume")
    return caminho


@app.local_entrypoint()
def main(
    preset: str = "",
    repo: str = "",
    arquivo: str = "",
    destino: str = "checkpoints",
):
    if preset:
        if preset not in PRESETS:
            disponiveis = ", ".join(PRESETS)
            raise SystemExit(f"Preset '{preset}' não existe. Disponíveis: {disponiveis}")
        for item in PRESETS[preset]:
            baixar.remote(item["repo"], item["arquivo"], item["destino"])
        print(f"\nPreset '{preset}' concluído.")
        return

    if not repo or not arquivo:
        raise SystemExit(
            "Informe --preset OU (--repo e --arquivo).\n"
            f"Presets disponíveis: {', '.join(PRESETS)}"
        )

    baixar.remote(repo, arquivo, destino)
    print("\nConcluído.")
