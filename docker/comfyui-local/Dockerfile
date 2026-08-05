FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git ComfyUI \
    && python -m pip install --upgrade pip \
    && python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision torchaudio \
    && sed -E '/^(torch|torchvision|torchaudio)([<=>].*)?$/d' ComfyUI/requirements.txt > /tmp/requirements.txt \
    && python -m pip install -r /tmp/requirements.txt \
    && python -m pip install modal

WORKDIR /opt/ComfyUI
EXPOSE 8188

CMD ["python", "main.py", "--cpu", "--listen", "0.0.0.0"]
