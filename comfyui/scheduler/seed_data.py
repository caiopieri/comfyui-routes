"""
Tabela semente de tempos médios de execução medidos (segundos).
Utilizada pelo Scheduler de GPU para estimativas antes de ter dados históricos suficientes no SQLite.
"""

from typing import Dict, Tuple

# Chave: (model_name, gpu_name, resolution, steps)
# Valor: tempo_execucao_segundos
SEED_BENCHMARKS: Dict[Tuple[str, str, str, int], float] = {
    # SDXL (1024x1024, 30 steps) — medido em execução real no Modal em
    # 2026-08-06 via generate_sdxl.py (container quente, tempo de inferência
    # puro, sem o load do checkpoint). A100-80GB e H100 seguem estimados
    # (não medidos nesta rodada — orçamento de calibração cobriu só até
    # A100-40GB).
    ("sdxl", "T4", "1024x1024", 30): 24.051,
    ("sdxl", "L4", "1024x1024", 30): 11.755,
    ("sdxl", "A10G", "1024x1024", 30): 9.868,
    ("sdxl", "A100-40GB", "1024x1024", 30): 4.309,
    ("sdxl", "A100-80GB", "1024x1024", 30): 3.8,
    ("sdxl", "H100", "1024x1024", 30): 2.5,

    # FLUX Schnell (1024x1024, 4 steps)
    ("flux_schnell", "T4", "1024x1024", 4): 12.0,
    ("flux_schnell", "L4", "1024x1024", 4): 5.5,
    ("flux_schnell", "A10G", "1024x1024", 4): 4.8,
    ("flux_schnell", "A100-40GB", "1024x1024", 4): 2.9,
    ("flux_schnell", "A100-80GB", "1024x1024", 4): 2.5,
    ("flux_schnell", "H100", "1024x1024", 4): 1.6,

    # FLUX Dev (1024x1024, 25 steps) - Não roda em T4 por causa de VRAM min
    ("flux_dev", "L4", "1024x1024", 25): 24.0,
    ("flux_dev", "A10G", "1024x1024", 25): 21.0,
    ("flux_dev", "A100-40GB", "1024x1024", 25): 11.5,
    ("flux_dev", "A100-80GB", "1024x1024", 25): 10.2,
    ("flux_dev", "H100", "1024x1024", 25): 6.8,

    # Wan 2.2 14B Video (720p, 81 frames, 30 steps) - Exige no mínimo 24GB VRAM
    ("wan_2_2_14b", "L4", "1280x720", 30): 95.0,
    ("wan_2_2_14b", "A10G", "1280x720", 30): 82.0,
    ("wan_2_2_14b", "A100-40GB", "1280x720", 30): 42.0,
    ("wan_2_2_14b", "A100-80GB", "1280x720", 30): 36.0,
    ("wan_2_2_14b", "H100", "1280x720", 30): 22.0,
}

def get_seed_estimate(model: str, gpu: str, resolution: str = "1024x1024", steps: int = 30) -> float:
    """Retorna tempo estimado da semente se disponível, ou uma aproximação padrão baseada nos steps."""
    exact_match = SEED_BENCHMARKS.get((model, gpu, resolution, steps))
    if exact_match is not None:
        return exact_match
    
    # Fallback por descalonamento proporcional a steps a partir de 30 steps
    base_match = SEED_BENCHMARKS.get((model, gpu, resolution, 30))
    if base_match is not None:
        return base_match * (steps / 30.0)
    
    # Generic fallback
    return 15.0 * (steps / 30.0)
