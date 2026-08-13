"""Cliente para o gateway local OmniRoute (http://localhost:20128).

Tenta gerar via API paga (modelos que o usuário já financia, tipo FLUX e
Alibaba/Qwen) antes de cair para GPU no Modal. Quem decide o modelo é o
usuário, no ComfyUI — este módulo só sabe: "esse nome de modelo tem rota
conhecida no OmniRoute?" Se não tiver, ou se a chamada falhar por qualquer
motivo (timeout, sem créditos, erro do provider), quem chamou deve cair
para o Modal — este módulo nunca decide isso sozinho, só levanta exceção.
"""

import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128")
OMNIROUTE_IMAGE_TIMEOUT_S = float(os.environ.get("OMNIROUTE_IMAGE_TIMEOUT_S", "45"))
OMNIROUTE_VIDEO_TIMEOUT_S = float(os.environ.get("OMNIROUTE_VIDEO_TIMEOUT_S", "240"))

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
# antes de entrar no mapa — não adicionar rota "no chute". IDs conferidos
# contra o registro-fonte do próprio OmniRoute (open-sse/config/
# imageRegistry.ts e videoRegistry.ts, v3.8.49) — usar outro ID do mesmo
# provider sem checar lá primeiro costuma dar "Unsupported ... model".
#
# response_format:
#   "b64_json" -> resposta já vem com os bytes (NVIDIA)
#   "url"      -> resposta vem com uma URL assinada pra baixar (Alibaba);
#                 baixamos e convertemos pra base64 aqui pra manter o mesmo
#                 formato de retorno pros dois casos.
# size_style:
#   "width_height" -> manda width/height como inteiros separados (NVIDIA)
#   "size_string"  -> manda "size": "1024x1024" como string (Alibaba)
#   None           -> modelo não usa tamanho (vídeo)
OMNIROUTE_MODEL_MAP = {
    "flux_dev": {
        "media_type": "image",
        "omniroute_model": "nvidia/black-forest-labs/flux.1-dev",
        "endpoint": "/v1/images/generations",
        "needs_placeholder_image": True,
        "size_style": "width_height",
        "response_format": "b64_json",
        "timeout_s": OMNIROUTE_IMAGE_TIMEOUT_S,
    },
    "qwen_image": {
        "media_type": "image",
        "omniroute_model": "alibaba/qwen-image-2.0",
        "endpoint": "/v1/images/generations",
        "needs_placeholder_image": False,
        "size_style": "size_string",
        "response_format": "url",
        "timeout_s": OMNIROUTE_IMAGE_TIMEOUT_S,
    },
    "wan_2_7": {
        "media_type": "video",
        "omniroute_model": "alibaba/wan2.7-t2v-2026-06-12",
        "endpoint": "/v1/videos/generations",
        "needs_placeholder_image": False,
        "size_style": None,
        "response_format": "url",
        "timeout_s": OMNIROUTE_VIDEO_TIMEOUT_S,
    },
    # Assinatura Google Pro (via conta OAuth do Antigravity já conectada no
    # OmniRoute) — não é a chave paga da API do AI Studio, que fica sem
    # crédito. Nano-banana de verdade.
    "nano_banana": {
        "media_type": "image",
        "omniroute_model": "antigravity/gemini-3.1-flash-image",
        "endpoint": "/v1/images/generations",
        "needs_placeholder_image": False,
        "size_style": "width_height",
        "response_format": "b64_json",
        "timeout_s": OMNIROUTE_IMAGE_TIMEOUT_S,
    },
    # Assinatura ChatGPT Plus (via conta OAuth do Codex já conectada no
    # OmniRoute) — não precisa de chave de API paga da OpenAI.
    "gpt_image": {
        "media_type": "image",
        "omniroute_model": "codex/gpt-5.6-sol",
        "endpoint": "/v1/images/generations",
        "needs_placeholder_image": False,
        "size_style": "width_height",
        "response_format": "url",
        "timeout_s": OMNIROUTE_IMAGE_TIMEOUT_S,
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


def _download_as_base64(url: str, default_format: str, timeout_s: float) -> tuple[str, str]:
    """Baixa o conteúdo de uma URL assinada (Alibaba) e devolve (base64, formato)."""
    import base64

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError(f"OmniRoute: falha ao baixar resultado ({error})") from error

    fmt = default_format
    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            fmt = guessed.lstrip(".")
    return base64.b64encode(raw).decode("ascii"), fmt


def generate_via_omniroute(model: str, prompt: str, width: int, height: int) -> dict:
    """Gera uma imagem ou vídeo via OmniRoute no mesmo formato de resumo que
    dispatch_workflow.py imprime para o path do Modal, para ser um drop-in
    na mesma leitura em remote_workflow_node.py. Lança exceção em qualquer
    falha — quem chama decide cair para o Modal."""
    spec = OMNIROUTE_MODEL_MAP[model]
    payload = {"model": spec["omniroute_model"], "prompt": prompt, "n": 1}
    if spec["size_style"] == "width_height":
        payload["width"] = width
        payload["height"] = height
    elif spec["size_style"] == "size_string":
        payload["size"] = f"{width}x{height}"
    if spec.get("needs_placeholder_image"):
        payload["image"] = f"data:image/png;base64,{_PLACEHOLDER_IMAGE_B64}"

    timeout_s = spec["timeout_s"]
    started = time.perf_counter()
    body = _post_json(spec["endpoint"], payload, timeout_s)
    duration_s = time.perf_counter() - started

    if "error" in body:
        raise RuntimeError(f"OmniRoute recusou {spec['omniroute_model']}: {body['error']}")
    data = body.get("data")
    if not data:
        raise RuntimeError(f"OmniRoute não retornou resultado: {body}")
    item = data[0]

    default_format = "mp4" if spec["media_type"] == "video" else "png"
    if spec["response_format"] == "b64_json":
        if "b64_json" not in item:
            raise RuntimeError(f"OmniRoute não retornou b64_json: {body}")
        data_base64 = item["b64_json"]
        output_format = item.get("format", default_format)
    else:  # "url"
        url = item.get("url")
        if not url:
            raise RuntimeError(f"OmniRoute não retornou URL: {body}")
        default_format = item.get("format", default_format)
        data_base64, output_format = _download_as_base64(url, default_format, timeout_s)

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
                "path": f"omniroute_{spec['omniroute_model'].replace('/', '_')}.{output_format}",
                "format": output_format,
                "data_base64": data_base64,
            }
        ],
    }
