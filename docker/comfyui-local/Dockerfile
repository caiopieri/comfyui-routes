FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ComfyUI

# Patch: register_file_in_place (app/assets/services/ingest.py) sempre marca
# a tag "uploaded" — é uma função pensada pra upload via browser, mas o
# ComfyUI 0.32 reaproveita ela em comfy_execution/asset_enrichment.py pra
# TODO output de execução (nativo ou de nó customizado), inclusive os
# gerados de verdade. Isso faz a aba "Gerado" do painel de Ativos (que
# filtra por essa tag) nunca mostrar nada, mesmo com job_id/prompt_id
# corretos no banco. Bug confirmado no código-fonte, não é do nosso nó —
# reportado upstream, patch aqui só até sair uma correção oficial.
RUN python3 - <<'PYEOF'
path = "/opt/ComfyUI/comfy_execution/asset_enrichment.py"
original = (
    '                result = register_file_in_place(\n'
    '                    abs_path=abs_path,\n'
    '                    name=entry["filename"],\n'
    '                    tags=[entry["type"]],\n'
    '                )\n'
)
patched = (
    '                result = register_file_in_place(\n'
    '                    abs_path=abs_path,\n'
    '                    name=entry["filename"],\n'
    '                    tags=[entry["type"]],\n'
    '                )\n'
    '                # Casa Amarano patch: ver comentário no Dockerfile.\n'
    '                try:\n'
    '                    from app.database.db import create_session\n'
    '                    from app.assets.database.queries.tags import remove_tags_from_reference\n'
    '                    with create_session() as _casa_amarano_session:\n'
    '                        remove_tags_from_reference(_casa_amarano_session, result.ref.id, ["uploaded"])\n'
    '                        _casa_amarano_session.commit()\n'
    '                except Exception:\n'
    '                    logging.warning("Casa Amarano: falha ao remover tag uploaded", exc_info=True)\n'
    '\n'
)
with open(path) as f:
    content = f.read()
assert original in content, "Trecho esperado não encontrado — ComfyUI mudou asset_enrichment.py, revisar o patch"
content = content.replace(original, patched, 1)
with open(path, "w") as f:
    f.write(content)
print("Patch aplicado em", path)
PYEOF

RUN python -m pip install --upgrade pip \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio \
    && sed -E '/^(torch|torchvision|torchaudio)([<=>].*)?$/d' ComfyUI/requirements.txt > /tmp/requirements.txt \
    && python -m pip install -r /tmp/requirements.txt \
    && python -m pip install modal

WORKDIR /opt/ComfyUI
EXPOSE 8188

CMD ["python", "main.py", "--cpu", "--listen", "0.0.0.0", "--enable-assets"]
