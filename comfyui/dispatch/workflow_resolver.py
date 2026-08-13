"""Descobre dependências de modelos de um workflow ComfyUI em formato API."""

import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from comfyui.modal_backend.config import GPU_SPECS, MODEL_PROFILES, canonical_model_name

# Modelo desconhecido (sem token cadastrado) mas com metadata properties.models
# no workflow (a mesma que a biblioteca oficial de templates do ComfyUI usa
# pro botão "Download Missing Models"): estima VRAM pelo tamanho real dos
# pesos em vez de cair num catálogo hand-curated que precisaria ser
# atualizado a cada modelo novo. Margem de 1.6x cobre ativações/overhead de
# runtime — não é medido, é uma folga de segurança; se ainda estourar OOM,
# o roteador (router.py) reaprende e escala pra GPU maior sozinho.
SIZE_ESTIMATE_SAFETY_MULTIPLIER = 1.6


MODEL_TOKENS = (
    ("wan_2_7", ("wan2.7", "wan_2.7", "wan-2.7")),
    ("qwen_image", ("qwen-image", "qwen_image")),
    ("nano_banana", ("nano-banana", "nano_banana", "nanobanana")),
    ("gpt_image", ("gpt-image", "gpt_image", "gptimage")),
    ("wan_2_2_14b", ("wan2.2", "wan_2.2", "wan-2.2")),
    ("wan_2_1_14b", ("wan2.1", "wan_2.1", "wan-2.1")),
    ("hunyuanvideo_1_5", ("hunyuanvideo-1.5", "hunyuanvideo_1_5")),
    ("hunyuanvideo", ("hunyuanvideo",)),
    ("flux2_dev", ("flux.2-dev", "flux2-dev", "flux2_dev")),
    ("flux2_klein_9b", ("flux.2-klein-9b", "flux2-klein-9b")),
    ("flux2_klein_4b", ("flux.2-klein-4b", "flux2-klein-4b")),
    ("flux_dev", ("flux1-dev", "flux-dev", "flux_dev")),
    ("flux_schnell", ("flux1-schnell", "flux-schnell", "flux_schnell")),
    ("cogvideox", ("cogvideox",)),
    ("ltx_video", ("ltx-video", "ltx_video", "ltx-2.3", "ltx_2.3", "ltx2.3")),
    ("mochi_1", ("mochi",)),
    ("sd15", ("v1-5", "sd1.5", "sd15")),
    ("sdxl", ("sdxl", "sd_xl", "stable-diffusion-xl")),
)


@dataclass(frozen=True)
class WorkflowResolution:
    model: str
    required_files: List[str]
    local_files: List[str]
    missing_files: List[str]
    execution_target: str
    vram_required_gb: int

    @property
    def needs_modal(self) -> bool:
        return self.execution_target == "modal"

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self) | {"needs_modal": self.needs_modal}


def _walk_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_values(child)


def _model_from_text(text: str) -> Optional[str]:
    lowered = text.lower().replace("\\", "/")
    for model, tokens in MODEL_TOKENS:
        if any(token in lowered for token in tokens):
            return model
    return None


def _required_files(workflow: Dict[str, Any]) -> List[str]:
    files = []
    for value in _walk_values(workflow):
        lowered = value.lower()
        if lowered.endswith((".safetensors", ".ckpt", ".pt", ".pth", ".bin")):
            files.append(value)
    return list(dict.fromkeys(files))


def extract_models_metadata(ui_workflow: Any) -> List[Dict[str, Any]]:
    """Percorre um workflow no formato UI (com `properties`) e coleta a
    metadata `properties.models` embutida pela biblioteca oficial de
    templates do ComfyUI (mesmo campo usado pelo botão nativo "Download
    Missing Models"). Espelha comfyui/modal_backend/download_models.py —
    duplicado ali de propósito (aquele arquivo roda sozinho dentro do
    Modal, sem o resto do pacote comfyui disponível)."""
    found: List[Dict[str, Any]] = []
    seen = set()

    def walk(node: Any) -> None:
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


def _tamanho_remoto(url: str) -> Optional[int]:
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=15) as response:
            content_length = response.headers.get("Content-Length")
            return int(content_length) if content_length else None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _estimate_vram_gb_from_metadata(models_metadata: List[Dict[str, Any]], fetch_sizes: bool) -> Optional[int]:
    total_bytes = 0
    for item in models_metadata:
        tamanho = item.get("size_bytes")
        if tamanho is None and fetch_sizes:
            tamanho = _tamanho_remoto(item["url"])
        if tamanho is None:
            return None  # não dá pra estimar com confiança se falta algum tamanho
        total_bytes += tamanho

    if total_bytes == 0:
        return None

    total_gb = total_bytes / (1024**3)
    estimado = total_gb * SIZE_ESTIMATE_SAFETY_MULTIPLIER
    tiers = sorted({spec["vram_gb"] for spec in GPU_SPECS.values()})
    for tier in tiers:
        if estimado <= tier:
            return tier
    return tiers[-1]  # nem a maior GPU do catálogo cobre a estimativa — deixa o router falhar com mensagem clara


def _synthetic_model_id(required_files: List[str]) -> str:
    """Identificador estável pro modelo desconhecido, baseado nos nomes dos
    arquivos referenciados — mesma combinação de arquivos sempre gera o
    mesmo id, então o aprendizado de VRAM/OOM no scheduler DB funciona
    mesmo sem cadastro manual no catálogo."""
    basenames = sorted(Path(f).name for f in required_files)
    digest = hashlib.sha1("|".join(basenames).encode("utf-8")).hexdigest()[:12]
    return f"auto_{digest}"


def resolve_workflow(
    workflow: Dict[str, Any],
    local_model_roots: Optional[Iterable[str | Path]] = None,
    models_metadata: Optional[List[Dict[str, Any]]] = None,
    fetch_sizes: bool = True,
) -> WorkflowResolution:
    """Resolve modelo e disponibilidade local sem baixar nem iniciar GPU.

    Quando o workflow não bate em nenhum token conhecido (MODEL_TOKENS) mas
    tem a metadata properties.models embutida (workflows da biblioteca
    oficial de templates), estima a VRAM pelo tamanho real dos pesos em vez
    de cair num catálogo hand-curated — isso evita precisar cadastrar cada
    modelo novo manualmente. Sem essa metadata, mantém o comportamento
    anterior (perfil "sdxl" como chute conservador — só cobre o caso raro de
    workflow desconhecido sem nenhuma pista)."""
    required = _required_files(workflow)
    text = " ".join(required) + " " + " ".join(_walk_values(workflow))
    token_model = _model_from_text(text)

    if token_model is not None:
        model = canonical_model_name(token_model)
        if model not in MODEL_PROFILES:
            raise ValueError(f"Família de modelo não catalogada: {model}")
        vram_gb = MODEL_PROFILES[model]["vram_min_gb"]
    else:
        estimado = _estimate_vram_gb_from_metadata(models_metadata or [], fetch_sizes)
        if estimado is not None:
            model = _synthetic_model_id(required)
            vram_gb = estimado
        else:
            model = canonical_model_name("sdxl")
            vram_gb = MODEL_PROFILES[model]["vram_min_gb"]

    roots = [Path(root).expanduser() for root in (local_model_roots or [])]
    local = []
    missing = []
    for filename in required:
        basename = Path(filename).name
        found = any((root / basename).exists() for root in roots)
        (local if found else missing).append(filename)

    return WorkflowResolution(
        model=model,
        required_files=required,
        local_files=local,
        missing_files=missing,
        execution_target="modal" if missing else "local",
        vram_required_gb=vram_gb,
    )
