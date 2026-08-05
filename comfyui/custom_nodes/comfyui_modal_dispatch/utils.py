"""
Utilitários de Serialização, Hash de Cache e Manipulação de Mídias
para o Nó Customizado ComfyUI Modal Dispatch.
"""

import hashlib
import json
import base64
import io
from typing import Dict, Any, Tuple


def compute_subgraph_hash(subgraph_json: Dict[str, Any], seed: int, params: Dict[str, Any]) -> str:
    """
    Gera um hash MD5 único determinístico a partir do subgrafo, seed e parâmetros.
    Garante idempotência e reaproveitamento de cache para inputs idênticos.
    """
    payload = {
        "subgraph": subgraph_json,
        "seed": seed,
        "params": params,
    }
    dumped = json.dumps(payload, sort_keys=True)
    return hashlib.md5(dumped.encode("utf-8")).hexdigest()


def base64_to_tensor(b64_string: str) -> Any:
    """
    Converte uma string Base64 em um formato representável como Image ou Placeholder.
    Em um ambiente ComfyUI completo, converte para torch.Tensor (NHWC [0..1]).
    """
    try:
        import torch
        from PIL import Image
        import numpy as np

        image_bytes = base64.b64decode(b64_string)
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr)[None, :]
        return tensor
    except ImportError:
        # Fallback se PyTorch não estiver no ambiente Python simples
        return f"[IMAGE_BASE64_BYTES_LEN_{len(b64_string)}]"


def create_video_reference_payload(filename: str, volume_path: str, url: str) -> str:
    """Gera a referência leve de vídeo em formato JSON."""
    return json.dumps({
        "media_type": "video",
        "filename": filename,
        "volume_path": volume_path,
        "url": url,
    })
