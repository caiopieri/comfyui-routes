"""Cliente para o gateway local OmniRoute (http://localhost:20128).

Tenta gerar via API paga (modelos que o usuário já financia, tipo FLUX)
antes de cair para GPU no Modal. Quem decide o modelo é o usuário, no
ComfyUI — este módulo só sabe: "esse nome de modelo tem rota conhecida no
OmniRoute?" Se não tiver, ou se a chamada falhar por qualquer motivo
(timeout, sem créditos, erro do provider), quem chamou deve cair para o
Modal — este módulo nunca decide isso sozinho, só levanta exceção.
"""

import json
import os
import time
import urllib.error
import urllib.request

OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128")
OMNIROUTE_TIMEOUT_S = float(os.environ.get("OMNIROUTE_TIMEOUT_S", "45"))

# PNG 1x1 usado só para satisfazer a validação de "image obrigatória" que
# alguns modelos FLUX da NVIDIA no OmniRoute exigem mesmo em txt2img puro.
# Confirmado em teste real (2026-08-11): o conteúdo da imagem é ignorado
# pelo provider — pedimos "pássaro vermelho" com esse placeholder e ele
# gerou o pássaro do zero, sem nenhuma relação com a imagem enviada.
_PLACEHOLDER_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

# Nome canônico de comfyui.modal_backend.config.MODEL_PROFILES -> como
# chamar no OmniRoute. Cada entrada aqui foi validada com uma chamada real
# (curl) antes de entrar no mapa — não adicionar rota "no chute". Ver
# HANDOFF.md para o histórico dos modelos testados e por que os outros
# variantes de FLUX (schnell, kontext-dev, klein-4b) e o OpenRouter ficaram
# de fora.
OMNIROUTE_MODEL_MAP = {
    "flux_dev": {
        "omniroute_model": "nvidia/black-forest-labs/flux.1-dev",
        "endpoint": "/v1/images/generations",
        "needs_placeholder_image": True,
    },
}


def has_omniroute_route(model: str) -> bool:
    return model in OMNIROUTE_MODEL_MAP


def _post_json(path: str, payload: dict, timeout_s: float) -> dict:
    url = f"{OMNIROUTE_BASE_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OmniRoute HTTP {error.code}: {body}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"OmniRoute inacessível ou timeout: {error}") from error


def generate_via_omniroute(model: str, prompt: str, width: int, height: int) -> dict:
    """Gera uma imagem via OmniRoute no mesmo formato de resumo que
    dispatch_workflow.py imprime para o path do Modal, para ser um drop-in
    na mesma leitura em remote_workflow_node.py. Lança exceção em qualquer
    falha — quem chama decide cair para o Modal."""
    spec = OMNIROUTE_MODEL_MAP[model]
    payload = {
        "model": spec["omniroute_model"],
        "prompt": prompt,
        "width": width,
        "height": height,
        "n": 1,
    }
    if spec.get("needs_placeholder_image"):
        payload["image"] = f"data:image/png;base64,{_PLACEHOLDER_IMAGE_B64}"

    started = time.perf_counter()
    body = _post_json(spec["endpoint"], payload, OMNIROUTE_TIMEOUT_S)
    duration_s = time.perf_counter() - started

    if "error" in body:
        raise RuntimeError(f"OmniRoute recusou {spec['omniroute_model']}: {body['error']}")
    data = body.get("data")
    if not data or "b64_json" not in data[0]:
        raise RuntimeError(f"OmniRoute não retornou imagem: {body}")

    return {
        "target": "omniroute",
        "model": model,
        "missing_files": [],
        "selected_gpu": None,
        "estimated_cost_usd": 0.0,
        "actual": {
            "provider": spec["omniroute_model"],
            "duration_s": round(duration_s, 3),
            # Custo real é debitado nos créditos do provedor (fora do
            # nosso controle/medição) — 0.0 aqui não significa "grátis",
            # significa "não rastreado por nós". Não usar para orçamento.
            "actual_cost_usd": 0.0,
            "is_warm": None,
        },
        "outputs": [
            {
                "path": f"omniroute_{spec['omniroute_model'].replace('/', '_')}.png",
                "format": "png",
                "data_base64": data[0]["b64_json"],
            }
        ],
    }
