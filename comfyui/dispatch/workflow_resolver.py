"""Descobre dependências de modelos de um workflow ComfyUI em formato API."""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from comfyui.modal_backend.config import MODEL_PROFILES, canonical_model_name


MODEL_TOKENS = (
    ("minimax_h3", ("minimax_h3", "minimax-h3")),
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


def resolve_workflow(
    workflow: Dict[str, Any],
    local_model_roots: Optional[Iterable[str | Path]] = None,
) -> WorkflowResolution:
    """Resolve modelo e disponibilidade local sem baixar nem iniciar GPU."""
    required = _required_files(workflow)
    text = " ".join(required) + " " + " ".join(_walk_values(workflow))
    model = _model_from_text(text) or "sdxl"
    model = canonical_model_name(model)
    if model not in MODEL_PROFILES:
        raise ValueError(f"Família de modelo não catalogada: {model}")

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
        vram_required_gb=MODEL_PROFILES[model]["vram_min_gb"],
    )
