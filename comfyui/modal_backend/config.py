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

# Requisitos de VRAM mínima por Modelo de IA (GB)
MODEL_VRAM_REQUIREMENTS: Dict[str, int] = {
    "sd15": 8,
    "sdxl": 12,
    "flux_schnell": 16,
    "flux_dev": 24,
    "wan_2_1_14b": 24,
    "wan_2_2_14b": 24,
    "cogvideox": 24,
    "ltx_video": 16,
}

# Limites Globais de Gasto e Defaults
DEFAULT_LAMBDA_HOURLY_VAL = float(os.getenv("COMFY_SCHEDULER_LAMBDA", "15.0"))  # USD/hora
DEFAULT_MONTHLY_BUDGET_CAP = float(os.getenv("COMFY_MONTHLY_BUDGET_CAP", "50.0"))  # USD/mês
DEFAULT_CONTAINER_IDLE_TIMEOUT = 300  # 5 minutos para iteração quente
MODEL_VOLUME_NAME = "comfyui-models-vol"
MODEL_MOUNT_DIR = "/models"
