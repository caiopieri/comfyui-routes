"""
Baixa modelos direto do Hugging Face para o Volume persistente do Modal.

Muito mais rápido que baixar na máquina local e fazer upload: o download
acontece na rede do datacenter e o arquivo nunca passa pela sua internet.

Uso:
    modal run comfyui/modal_backend/download_models.py --preset sdxl
    modal run comfyui/modal_backend/download_models.py --preset flux-schnell
    modal run comfyui/modal_backend/download_models.py --repo <repo> --arquivo <file> --destino checkpoints

    # Lê a metadata properties.models embutida num workflow (formato UI,
    # com o que a biblioteca oficial de templates do ComfyUI já usa pro
    # botão "Download Missing Models"), mostra tamanho e pede confirmação
    # antes de baixar pro volume:
    modal run comfyui/modal_backend/download_models.py --workflow-file caminho/workflow.json
    modal run comfyui/modal_backend/download_models.py --workflow-file caminho/workflow.json --yes  # sem prompt

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
    "ltx-2.3-i2v": [
        {
            "repo": "Lightricks/LTX-2.3-fp8",
            "arquivo": "ltx-2.3-22b-dev-fp8.safetensors",
            "destino": "checkpoints",
        },
        {
            "repo": "Comfy-Org/ltx-2",
            "arquivo": "gemma_3_12B_it_fp4_mixed.safetensors",
            "hf_arquivo": "split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors",
            "destino": "text_encoders",
        },
        {
            "repo": "Comfy-Org/ltx-2",
            "arquivo": "gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors",
            "hf_arquivo": "split_files/loras/gemma-3-12b-it-abliterated_lora_rank64_bf16.safetensors",
            "destino": "loras",
        },
        {
            "repo": "Kijai/LTX2.3_comfy",
            "arquivo": "ltx_2.3_22b_distilled_1.1_lora_dynamic_fro09_avg_rank_111_bf16.safetensors",
            "hf_arquivo": "loras/ltx-2.3-22b-distilled-1.1_lora-dynamic_fro09_avg_rank_111_bf16.safetensors",
            "destino": "loras",
        },
        {
            "repo": "Lightricks/LTX-2.3",
            "arquivo": "ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
            "destino": "latent_upscale_models",
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
def baixar(repo: str, arquivo: str, destino: str = "checkpoints", hf_arquivo: str = ""):
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
        filename=hf_arquivo or arquivo,
        local_dir=pasta,
        token=os.environ.get("HF_TOKEN"),
    )
    if os.path.abspath(caminho) != os.path.abspath(destino_final):
        os.replace(caminho, destino_final)
        caminho = destino_final

    volume.commit()
    tamanho = os.path.getsize(caminho) / (1024**3)
    print(f"[ok] {arquivo} — {tamanho:.1f} GB gravado no volume")
    return caminho


@app.function(
    image=image,
    volumes={MODEL_MOUNT_DIR: volume},
    timeout=60 * 60,
    secrets=[modal.Secret.from_name("huggingface", required_keys=[])],
)
def baixar_url(url: str, destino: str, arquivo: str):
    """Baixa um arquivo de uma URL direta (a metadata `properties.models`
    que o próprio ComfyUI embute nos workflows da biblioteca oficial, com
    link já resolvido) direto pro volume, em streaming."""
    import os
    import urllib.request

    pasta = os.path.join(MODEL_MOUNT_DIR, destino)
    os.makedirs(pasta, exist_ok=True)
    destino_final = os.path.join(pasta, arquivo)
    if os.path.exists(destino_final):
        tamanho = os.path.getsize(destino_final) / (1024**3)
        print(f"[pular] {arquivo} já existe ({tamanho:.1f} GB)")
        return destino_final

    print(f"[baixando] {url} -> {pasta}")
    headers = {}
    token = os.environ.get("HF_TOKEN")
    if token and "huggingface.co" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    parcial = destino_final + ".part"
    with urllib.request.urlopen(request) as response, open(parcial, "wb") as f:
        while True:
            chunk = response.read(8 * 1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    os.replace(parcial, destino_final)

    volume.commit()
    tamanho = os.path.getsize(destino_final) / (1024**3)
    print(f"[ok] {arquivo} — {tamanho:.1f} GB gravado no volume")
    return destino_final


def _extract_workflow_models(ui_workflow: dict) -> list:
    """Percorre um workflow no formato UI (com `properties`) e coleta a
    metadata `properties.models` que o próprio ComfyUI embute nos workflows
    da biblioteca oficial de templates — mesmo campo que alimenta o botão
    "Download Missing Models" nativo. Workflows da comunidade sem essa
    metadata não têm URL confiável pra descobrir; não adivinhamos."""
    found = []
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            props = node.get("properties")
            models = props.get("models") if isinstance(props, dict) else None
            if isinstance(models, list):
                for item in models:
                    name = item.get("name") if isinstance(item, dict) else None
                    url = item.get("url") if isinstance(item, dict) else None
                    if name and url and name not in seen:
                        seen.add(name)
                        found.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(ui_workflow)
    return found


def _tamanho_remoto(url: str) -> int | None:
    import urllib.request

    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=15) as response:
            content_length = response.headers.get("Content-Length")
            return int(content_length) if content_length else None
    except Exception:
        return None


@app.local_entrypoint()
def main(
    preset: str = "",
    repo: str = "",
    arquivo: str = "",
    destino: str = "checkpoints",
    workflow_file: str = "",
    yes: bool = False,
):
    if workflow_file:
        import json
        from pathlib import Path

        ui_workflow = json.loads(Path(workflow_file).read_text(encoding="utf-8"))
        modelos = _extract_workflow_models(ui_workflow)
        if not modelos:
            print(
                "Nenhuma metadata de modelo (properties.models) encontrada nesse "
                "workflow.\nIsso é normal em workflows da comunidade sem essa "
                "informação embutida — nesse caso não dá pra descobrir a URL "
                "certa automaticamente; baixe manualmente com --repo/--arquivo."
            )
            return

        print(f"{len(modelos)} modelo(s) referenciado(s) no workflow:\n")
        total_bytes = 0
        for item in modelos:
            tamanho = _tamanho_remoto(item["url"])
            item["_tamanho_bytes"] = tamanho
            if tamanho:
                total_bytes += tamanho
            tamanho_str = f"{tamanho / (1024**3):.2f} GB" if tamanho else "tamanho desconhecido"
            destino_item = item.get("directory", "checkpoints")
            print(f"  - {item['name']} ({tamanho_str}) -> {destino_item}")

        if total_bytes:
            print(f"\nTotal estimado: {total_bytes / (1024**3):.2f} GB no Volume do Modal")
        else:
            print("\nNão foi possível estimar o tamanho de um ou mais arquivos.")

        if not yes:
            resposta = input("\nConfirmar download pro Volume do Modal? [s/N] ").strip().lower()
            if resposta not in ("s", "sim", "y", "yes"):
                print("Cancelado — nada foi baixado.")
                return

        for item in modelos:
            baixar_url.remote(item["url"], item.get("directory", "checkpoints"), item["name"])
        print(f"\n{len(modelos)} modelo(s) baixado(s) pro volume.")
        return

    if preset:
        if preset not in PRESETS:
            disponiveis = ", ".join(PRESETS)
            raise SystemExit(f"Preset '{preset}' não existe. Disponíveis: {disponiveis}")
        for item in PRESETS[preset]:
            baixar.remote(item["repo"], item["arquivo"], item["destino"], item.get("hf_arquivo", item["arquivo"]))
        print(f"\nPreset '{preset}' concluído.")
        return

    if not repo or not arquivo:
        raise SystemExit(
            "Informe --preset OU (--repo e --arquivo).\n"
            f"Presets disponíveis: {', '.join(PRESETS)}"
        )

    baixar.remote(repo, arquivo, destino)
    print("\nConcluído.")
