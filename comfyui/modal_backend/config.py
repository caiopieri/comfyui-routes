"""
Configurações do Modal Backend e Scheduler de GPU do Casa Amarano.
Preços de GPU em USD por hora e por segundo (Modal.com).
"""

import os
from typing import Dict, Any

# Tabela de especificações e preços de GPUs no Modal (USD)
# Atualizável via arquivo de config ou variáveis de ambiente sem alterar código.
GPU_SPECS: Dict[str, Dict[str, Any]] = {
    "T4": {
        "vram_gb": 16,
        "price_per_hour": 0.59,
        "price_per_sec": 0.59 / 3600.0,
        "default_cold_start_s": 25.0,
        "modal_gpu_name": "t4",
    },
    "L4": {
        "vram_gb": 24,
        "price_per_hour": 0.80,
        "price_per_sec": 0.80 / 3600.0,
        "default_cold_start_s": 20.0,
        "modal_gpu_name": "l4",
    },
    "A10G": {
        "vram_gb": 24,
        "price_per_hour": 1.10,
        "price_per_sec": 1.10 / 3600.0,
        "default_cold_start_s": 18.0,
        "modal_gpu_name": "a10g",
    },
    "A100-40GB": {
        "vram_gb": 40,
        "price_per_hour": 2.10,
        "price_per_sec": 2.10 / 3600.0,
        "default_cold_start_s": 15.0,
        "modal_gpu_name": "a100-40gb",
    },
    "A100-80GB": {
        "vram_gb": 80,
        "price_per_hour": 2.50,
        "price_per_sec": 2.50 / 3600.0,
        "default_cold_start_s": 15.0,
        "modal_gpu_name": "a100-80gb",
    },
    "H100": {
        "vram_gb": 80,
        "price_per_hour": 3.95,
        "price_per_sec": 3.95 / 3600.0,
        "default_cold_start_s": 12.0,
        "modal_gpu_name": "h100",
    },
}

# Catálogo de famílias usadas pelo nó. O requisito é deliberadamente
# conservador: inclui folga para pesos, VAE, activations e ComfyUI.
# Não representa todos os checkpoints da comunidade; checkpoints da mesma
# família usam o mesmo perfil (por exemplo, RealVisXL -> sdxl).
MODEL_PROFILES: Dict[str, Dict[str, Any]] = {
    "sd15": {"family": "Stable Diffusion 1.5", "mode": "txt2img/img2img", "vram_min_gb": 8},
    "sdxl": {"family": "Stable Diffusion XL", "mode": "txt2img/img2img", "vram_min_gb": 12},
    "flux_schnell": {"family": "FLUX.1 schnell", "mode": "txt2img", "vram_min_gb": 16},
    "flux_dev": {"family": "FLUX.1 dev", "mode": "txt2img", "vram_min_gb": 24},
    "flux_fill": {"family": "FLUX.1 Fill", "mode": "inpaint", "vram_min_gb": 24},
    "flux_kontext": {"family": "FLUX.1 Kontext", "mode": "image editing", "vram_min_gb": 24},
    "flux2_klein_4b": {"family": "FLUX.2 klein 4B", "mode": "txt2img/image editing", "vram_min_gb": 8},
    "flux2_klein_9b": {"family": "FLUX.2 klein 9B", "mode": "txt2img/image editing", "vram_min_gb": 16},
    "flux2_dev": {"family": "FLUX.2 dev", "mode": "txt2img/image editing", "vram_min_gb": 80},
    "wan_2_1_t2v_1_3b": {"family": "Wan 2.1 T2V 1.3B", "mode": "txt2video", "vram_min_gb": 10},
    "wan_2_1_14b": {"family": "Wan 2.1 14B", "mode": "txt2video/img2video", "vram_min_gb": 40},
    "wan_2_2_14b": {"family": "Wan 2.2 T2V A14B", "mode": "txt2video", "vram_min_gb": 80},
    "hunyuanvideo_1_5": {"family": "HunyuanVideo 1.5", "mode": "txt2video/img2video", "vram_min_gb": 16},
    "hunyuanvideo": {"family": "HunyuanVideo", "mode": "txt2video/img2video", "vram_min_gb": 64},
    "cogvideox": {"family": "CogVideoX", "mode": "txt2video/img2video", "vram_min_gb": 32},
    "ltx_video": {"family": "LTX-2.3 22B", "mode": "txt2video/img2video", "vram_min_gb": 40},
    "mochi_1": {"family": "Mochi 1", "mode": "txt2video", "vram_min_gb": 24},
    "upscale_4x": {"family": "Upscale 4x", "mode": "upscale", "vram_min_gb": 8},
}

# Compatibilidade com o roteador e com integrações existentes.
MODEL_VRAM_REQUIREMENTS: Dict[str, int] = {
    name: profile["vram_min_gb"] for name, profile in MODEL_PROFILES.items()
}

MODEL_ALIASES = {
    "wan2.1_1.3b": "wan_2_1_t2v_1_3b",
    "wan_2_1_1_3b": "wan_2_1_t2v_1_3b",
    "wan2.1_14b": "wan_2_1_14b",
    "wan2.2_14b": "wan_2_2_14b",
    "hunyuanvideo_1.5": "hunyuanvideo_1_5",
    "flux2_klein_4b": "flux2_klein_4b",
}

def canonical_model_name(model: str) -> str:
    """Normaliza aliases do nó/API para um perfil conhecido."""
    normalized = model.strip().lower().replace("-", "_")
    return MODEL_ALIASES.get(normalized, normalized)

# Limites Globais de Gasto e Defaults
# Perfil de aprendizado: 3.0 USD/h dá algum peso a tempo sem empurrar pra GPU
# cara à toa (15.0 é perfil de produção com pressa, não usar sem necessidade).
DEFAULT_LAMBDA_HOURLY_VAL = float(os.getenv("COMFY_SCHEDULER_LAMBDA", "3.0"))  # USD/hora
DEFAULT_MONTHLY_BUDGET_CAP = float(os.getenv("COMFY_MONTHLY_BUDGET_CAP", "50.0"))  # USD/mês
DEFAULT_CONTAINER_IDLE_TIMEOUT = 300  # 5 minutos para iteração quente
MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"
