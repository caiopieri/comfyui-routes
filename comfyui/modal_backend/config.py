"""
Configurações do Modal Backend e Scheduler de GPU do Casa Amarano.
Preços de GPU em USD por hora e por segundo (Modal.com).
"""

import os
from typing import Dict, Any

# Tabela de especificações e preços de GPUs no Modal (USD)
# Atualizável via arquivo de config ou variáveis de ambiente sem alterar código.
#
# default_cold_start_s medido em 2026-08-06 via generate_sdxl.py (container
# frio, primeira chamada): tempo de carregar o checkpoint SDXL (~6.5GB fp16)
# do Volume pra VRAM, sem contar a inferência em si (essa vai em
# seed_data.py). Modelos maiores (vídeo, FLUX.2 dev etc.) vão pesar mais que
# isso — não extrapolar direto sem medir. A100-80GB/H100 não foram medidos
# nesta rodada (orçamento de calibração cobriu só até A100-40GB); mantidos
# como estimativa anterior.
GPU_SPECS: Dict[str, Dict[str, Any]] = {
    "T4": {
        "vram_gb": 16,
        "price_per_hour": 0.59,
        "price_per_sec": 0.59 / 3600.0,
        "default_cold_start_s": 9.3,
        "modal_gpu_name": "t4",
    },
    "L4": {
        "vram_gb": 24,
        "price_per_hour": 0.80,
        "price_per_sec": 0.80 / 3600.0,
        "default_cold_start_s": 7.3,
        "modal_gpu_name": "l4",
    },
    "A10G": {
        "vram_gb": 24,
        "price_per_hour": 1.10,
        "price_per_sec": 1.10 / 3600.0,
        "default_cold_start_s": 7.0,
        "modal_gpu_name": "a10g",
    },
    "A100-40GB": {
        "vram_gb": 40,
        "price_per_hour": 2.10,
        "price_per_sec": 2.10 / 3600.0,
        "default_cold_start_s": 6.2,
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
    # 80GB mantido de propósito: não há preset de download nem arquivo no
    # Volume pra medir de verdade (fp16 do Wan 2.2 14B ficaria perto de 28GB
    # só em pesos). Não baixar/reduzir sem medir primeiro.
    "wan_2_2_14b": {"family": "Wan 2.2 T2V A14B", "mode": "txt2video", "vram_min_gb": 80},
    "hunyuanvideo_1_5": {"family": "HunyuanVideo 1.5", "mode": "txt2video/img2video", "vram_min_gb": 16},
    "hunyuanvideo": {"family": "HunyuanVideo", "mode": "txt2video/img2video", "vram_min_gb": 64},
    "cogvideox": {"family": "CogVideoX", "mode": "txt2video/img2video", "vram_min_gb": 32},
    # 40GB media curto: checkpoint fp8 (27.1 GiB) + text encoder gemma fp4
    # (8.8 GiB) medidos no Volume (`modal volume ls`) já somam ~36 GiB só em
    # pesos, antes de ativações/VAE/overhead do ComfyUI. 64GB dá folga real.
    "ltx_video": {"family": "LTX-2.3 22B", "mode": "txt2video/img2video", "vram_min_gb": 64},
    "mochi_1": {"family": "Mochi 1", "mode": "txt2video", "vram_min_gb": 24},
    "upscale_4x": {"family": "Upscale 4x", "mode": "upscale", "vram_min_gb": 8},
    # Cloud-only via OmniRoute (Alibaba/DashScope) — não há preset de
    # download nem checkpoint local pra medir de verdade. vram_min_gb aqui
    # é só um chute conservador para o fallback no Modal ter algum número;
    # esse fallback só funciona de verdade se você tiver pesos locais
    # equivalentes instalados (não vêm com o projeto). Ver omniroute_client.py.
    "qwen_image": {"family": "Qwen Image 2.0 (Alibaba)", "mode": "txt2img", "vram_min_gb": 24},
    "wan_2_7": {"family": "Wan 2.7 (Alibaba)", "mode": "txt2video", "vram_min_gb": 80},
    # Idem, só que via assinatura (Google Pro / ChatGPT Plus) através do
    # OAuth já conectado no OmniRoute — sem checkpoint local equivalente.
    "nano_banana": {"family": "Nano Banana / Gemini 3.1 Flash Image", "mode": "txt2img", "vram_min_gb": 16},
    "gpt_image": {"family": "GPT Image (via Codex/ChatGPT Plus)", "mode": "txt2img", "vram_min_gb": 24},
    # Medido na prática (2026-08-12): sem essa entrada o resolvedor caía no
    # default "sdxl" (12GB) e o roteador escolhia GPU pequena demais — deu
    # torch.OutOfMemoryError carregando só o text encoder (14.6GB de pesos
    # quantizados NVFP4, já reservando 14.4GB antes mesmo do UNET de
    # 19.53GB e das VAEs entrarem). 80GB é o teto do catálogo; ainda não
    # confirmamos se cabe justo ou se precisa de offload — só sabemos que
    # T4/L4/A10G (16-24GB) não servem.
    "minimax_h3": {"family": "MiniMax H3 (vídeo)", "mode": "img2video/txt2video", "vram_min_gb": 80},
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
