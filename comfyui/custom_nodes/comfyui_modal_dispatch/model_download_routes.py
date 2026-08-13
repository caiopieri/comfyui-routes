"""Rotas HTTP pra checar tamanho e disparar download de modelos faltantes
pro Volume do Modal, direto da interface do ComfyUI (sem precisar pedir
pra rodar nada manualmente)."""

import asyncio
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

CASA_AMARANO_ROOT = os.environ.get(
    "CASA_AMARANO_ROOT", "/Users/caioamaraldepieri/Projetos/Casa Amarano"
)
DOWNLOAD_SCRIPT = os.path.join(
    CASA_AMARANO_ROOT, "comfyui", "modal_backend", "download_models.py"
)

_download_jobs = {}


def _tamanho_remoto(url: str):
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=15) as response:
            content_length = response.headers.get("Content-Length")
            return int(content_length) if content_length else None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def _run_download_job(job_id: str, workflow_path: str):
    try:
        completed = subprocess.run(
            ["modal", "run", DOWNLOAD_SCRIPT, "--workflow-file", workflow_path, "--yes"],
            cwd=CASA_AMARANO_ROOT,
            capture_output=True,
            text=True,
            timeout=60 * 60,
        )
        _download_jobs[job_id] = {
            "status": "done" if completed.returncode == 0 else "error",
            "output": (completed.stdout or "")[-4000:],
            "error": (completed.stderr or "")[-4000:] if completed.returncode != 0 else None,
        }
    except Exception as error:  # subprocess/timeout falhas viram status "error" pro front conseguir mostrar
        _download_jobs[job_id] = {"status": "error", "output": "", "error": str(error)}
    finally:
        try:
            os.unlink(workflow_path)
        except OSError:
            pass


def register_routes(prompt_server):
    routes = prompt_server.routes

    @routes.post("/casa_amarano/missing_models_info")
    async def missing_models_info(request):
        body = await request.json()
        modelos = body.get("models", [])
        resultado = []
        for item in modelos:
            nome = item.get("name")
            url = item.get("url")
            if not nome or not url:
                continue
            tamanho = _tamanho_remoto(url)
            resultado.append(
                {
                    "name": nome,
                    "url": url,
                    "directory": item.get("directory", "checkpoints"),
                    "size_bytes": tamanho,
                }
            )
        from aiohttp import web

        return web.json_response({"models": resultado})

    @routes.post("/casa_amarano/download_models")
    async def download_models(request):
        from aiohttp import web

        body = await request.json()
        modelos = body.get("models", [])
        if not modelos:
            return web.json_response({"error": "Nenhum modelo informado"}, status=400)

        workflow_payload = {
            "nodes": [
                {"properties": {"models": modelos}},
            ]
        }
        fd, workflow_path = tempfile.mkstemp(prefix="casa-amarano-download-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(workflow_payload, f)

        job_id = os.path.basename(workflow_path)
        _download_jobs[job_id] = {"status": "running", "output": "", "error": None}
        asyncio.get_event_loop().run_in_executor(
            None, _run_download_job, job_id, workflow_path
        )
        return web.json_response({"job_id": job_id, "status": "running"})

    @routes.get("/casa_amarano/download_models/{job_id}")
    async def download_models_status(request):
        from aiohttp import web

        job_id = request.match_info["job_id"]
        job = _download_jobs.get(job_id)
        if job is None:
            return web.json_response({"error": "job não encontrado"}, status=404)
        return web.json_response(job)


def _register():
    try:
        from server import PromptServer
    except ImportError:
        return
    register_routes(PromptServer.instance)


_register()
