"""Fallback transparente para workflows cujos modelos não estão no Mac."""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import uuid
from pathlib import Path

from .utils import base64_to_tensor

CASA_AMARANO_ROOT = Path(os.environ.get("CASA_AMARANO_ROOT", "/workspace/project"))
DISPATCH_SCRIPT = CASA_AMARANO_ROOT / "comfyui" / "modal_backend" / "dispatch_workflow.py"


def _walk(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, str):
        yield value


def _workflow_value(workflow, names, default):
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        for name in names:
            if name in inputs and isinstance(inputs[name], (int, float)):
                return inputs[name]
    return default


def _resolution(workflow):
    width = int(_workflow_value(workflow, ("width",), 1280))
    height = int(_workflow_value(workflow, ("height",), 720))
    return f"{width}x{height}"


def _prompt_text(workflow):
    """Acha o texto do prompt positivo: segue o link 'positive' do KSampler
    até o CLIPTextEncode de origem; se não achar, usa o primeiro
    CLIPTextEncode com texto no workflow."""
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "KSampler":
            continue
        positive_ref = node.get("inputs", {}).get("positive")
        if isinstance(positive_ref, list) and positive_ref:
            source = workflow.get(str(positive_ref[0]))
            if isinstance(source, dict):
                text = source.get("inputs", {}).get("text")
                if isinstance(text, str):
                    return text
    for node in workflow.values():
        if isinstance(node, dict) and node.get("class_type") == "CLIPTextEncode":
            text = node.get("inputs", {}).get("text")
            if isinstance(text, str):
                return text
    return "a photorealistic image"


def _try_omniroute(workflow):
    """Se o modelo resolvido do workflow tem rota conhecida no OmniRoute,
    tenta gerar por lá primeiro. Retorna None (não None = sucesso) para
    cair no Modal em qualquer falha ou ausência de rota."""
    try:
        from comfyui.dispatch.workflow_resolver import resolve_workflow
        from comfyui.modal_backend.omniroute_client import (
            has_omniroute_route,
            generate_via_omniroute,
        )
    except ImportError:
        return None
    model = resolve_workflow(workflow).model
    if not has_omniroute_route(model):
        return None
    width = int(_workflow_value(workflow, ("width",), 1024))
    height = int(_workflow_value(workflow, ("height",), 1024))
    prompt = _prompt_text(workflow)
    try:
        print(f"[OmniRoute] Tentando {model} via API antes da GPU no Modal...")
        return generate_via_omniroute(model, prompt, width, height)
    except Exception as error:
        print(f"[OmniRoute] Falhou ({error}) — caindo para GPU no Modal.")
        return None


def _collect_input_files(workflow):
    """Serializa imagens carregadas localmente para o job remoto."""
    try:
        import folder_paths
    except ImportError:
        return {}
    files = {}
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        filename = node.get("inputs", {}).get("image")
        if not isinstance(filename, str) or filename.startswith("http"):
            continue
        try:
            source = Path(folder_paths.get_annotated_filepath(filename))
            if source.exists():
                files[source.name] = base64.b64encode(source.read_bytes()).decode("ascii")
                node["inputs"]["image"] = source.name
        except (OSError, ValueError):
            continue
    return files


def _run_remote(workflow_json, models_metadata_json="[]"):
    workflow = json.loads(workflow_json)
    omniroute_result = _try_omniroute(workflow)
    if omniroute_result is not None:
        return omniroute_result
    try:
        models_metadata = json.loads(models_metadata_json)
    except json.JSONDecodeError:
        models_metadata = []
    input_files = _collect_input_files(workflow)
    import folder_paths
    with tempfile.TemporaryDirectory(prefix="casa-modal-") as temp_dir:
        workflow_path = Path(temp_dir) / "workflow.json"
        manifest_path = Path(temp_dir) / "manifest.json"
        workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
        manifest_path.write_text(
            json.dumps({"workflow": workflow, "input_files": input_files, "models_metadata": models_metadata}),
            encoding="utf-8",
        )
        command = [
            "modal", "run", str(DISPATCH_SCRIPT), "--workflow-file", str(workflow_path),
            "--lambda-val", str(os.environ.get("COMFY_MODAL_LAMBDA", "0")),
            "--resolution", _resolution(workflow),
            "--steps", str(int(_workflow_value(workflow, ("steps", "num_inference_steps"), 20))),
            # folder_paths.models_dir é a própria noção do ComfyUI de "onde
            # estão meus modelos" — funciona igual em Docker, Desktop ou
            # instalação nua. "/opt/ComfyUI/models" só existia por coincidir
            # com o layout do nosso container; fora dele, sempre reportava
            # tudo como ausente (mesmo quando não era o caso).
            "--local-model-root", str(folder_paths.models_dir),
            "--input-manifest", str(manifest_path),
        ]
        try:
            completed = subprocess.run(command, cwd=str(CASA_AMARANO_ROOT), check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Modal falhou (exit={error.returncode}): {(error.stderr or error.stdout)[-4000:]}") from error
        for line in reversed(completed.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value.get("actual") and value.get("outputs"):
                return value
        raise RuntimeError(f"Modal não retornou um resultado válido: {completed.stdout[-3000:]}")


class _RemoteBase:
    CATEGORY = "Casa Amarano / Modal"
    FUNCTION = "execute"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"workflow_json": ("STRING", {"multiline": True})},
            "optional": {"models_metadata_json": ("STRING", {"multiline": True, "default": "[]"})},
        }

    def _result(self, workflow_json, models_metadata_json="[]"):
        started = time.perf_counter()
        result = _run_remote(workflow_json, models_metadata_json)
        output = result["outputs"][0]
        output_path = Path(output["path"])
        fd, local_path = tempfile.mkstemp(prefix="casa-modal-output-", suffix=f".{output['format']}")
        os.close(fd)
        output_path = Path(local_path)
        output_path.write_bytes(base64.b64decode(output["data_base64"]))
        return result, output_path, time.perf_counter() - started


def _publish_output(source):
    import folder_paths
    output_dir = Path(folder_paths.get_output_directory())
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"casa_amarano_modal_{uuid.uuid4().hex[:10]}{source.suffix}"
    shutil.copyfile(source, target)
    return target


class ModalRemoteImageWorkflow(_RemoteBase):
    RETURN_TYPES = ("IMAGE", "STRING", "FLOAT", "FLOAT")
    RETURN_NAMES = ("image", "dispatch_info", "duration_seconds", "cost_usd")

    def execute(self, workflow_json, models_metadata_json="[]"):
        result, output_path, duration = self._result(workflow_json, models_metadata_json)
        published = _publish_output(output_path)
        data = base64.b64encode(output_path.read_bytes()).decode("ascii")
        ui = {"images": [{"filename": published.name, "subfolder": "", "type": "output"}]}
        values = (base64_to_tensor(data), json.dumps(result, ensure_ascii=False), duration, float(result["actual"]["actual_cost_usd"]))
        return {"ui": ui, "result": values}


class ModalRemoteVideoWorkflow(_RemoteBase):
    RETURN_TYPES = ("VIDEO", "STRING", "FLOAT", "FLOAT")
    RETURN_NAMES = ("video", "dispatch_info", "duration_seconds", "cost_usd")

    def execute(self, workflow_json, models_metadata_json="[]"):
        result, output_path, duration = self._result(workflow_json, models_metadata_json)
        published = _publish_output(output_path)
        from comfy_api.latest import InputImpl
        # "gifs" era a convenção antiga do ComfyUI para vídeo/animado, mas o
        # /api/jobs do core (comfy_execution/jobs.py, PREVIEWABLE_MEDIA_TYPES)
        # não reconhece essa chave — só conta como previewable outputs sob
        # "images" (mesmo pra vídeo, com animated=True), que é o formato que
        # o próprio SaveVideo/PreviewVideo nativo usa.
        ui = {"images": [{"filename": published.name, "subfolder": "", "type": "output"}], "animated": (True,)}
        values = (InputImpl.VideoFromFile(str(published)), json.dumps(result, ensure_ascii=False), duration, float(result["actual"]["actual_cost_usd"]))
        return {"ui": ui, "result": values}


class ModalRemote3DWorkflow(_RemoteBase):
    # Retorna o caminho como STRING em vez de tentar decodificar o arquivo
    # (GLB/OBJ/etc.) como imagem — base64_to_tensor (utils.py) usa
    # PIL.Image.open, que não entende esses formatos. "3d" é a mesma chave
    # de UI que o SaveGLB nativo usa (comfy_extras/nodes_save_3d.py).
    RETURN_TYPES = ("STRING", "STRING", "FLOAT", "FLOAT")
    RETURN_NAMES = ("model_3d_path", "dispatch_info", "duration_seconds", "cost_usd")

    def execute(self, workflow_json, models_metadata_json="[]"):
        result, output_path, duration = self._result(workflow_json, models_metadata_json)
        published = _publish_output(output_path)
        ui = {"3d": [{"filename": published.name, "subfolder": "", "type": "output"}]}
        values = (str(published), json.dumps(result, ensure_ascii=False), duration, float(result["actual"]["actual_cost_usd"]))
        return {"ui": ui, "result": values}


def install_prompt_fallback():
    """Troca workflows incompletos por um nó remoto antes da validação local."""
    try:
        from server import PromptServer
        from comfyui.dispatch.workflow_resolver import resolve_workflow, extract_models_metadata
        import folder_paths
    except ImportError:
        return

    def on_prompt(payload):
        workflow = payload.get("prompt")
        if not isinstance(workflow, dict) or any(
            node.get("class_type", "").startswith("ModalRemote")
            for node in workflow.values() if isinstance(node, dict)
        ):
            return payload
        try:
            # folder_paths.models_dir é portátil (Docker/Desktop/instalação
            # nua); o segundo caminho é o diretório de modelos do próprio
            # repo, relativo a CASA_AMARANO_ROOT (respeitando a env var, em
            # vez de "/workspace/project" fixo, que só existe no container).
            resolution = resolve_workflow(
                workflow,
                [folder_paths.models_dir, str(CASA_AMARANO_ROOT / "comfyui" / "models")],
            )
        except (TypeError, ValueError):
            return payload
        if not resolution.needs_modal or not resolution.missing_files:
            return payload
        video = any(
            isinstance(node, dict) and (
                node.get("class_type") in {"SaveVideo", "LTXVImgToVideo", "LTXVTextToVideo"}
                or "video" in node.get("class_type", "").lower()
            )
            for node in workflow.values()
        )
        video = video or any("ltx" in text.lower() for text in _walk(workflow))
        is_3d = any(
            isinstance(node, dict) and (
                node.get("class_type") in {
                    "SaveGLB", "Save3DAdvanced", "SaveGaussianSplat", "SavePointCloud",
                }
                or "3d" in node.get("class_type", "").lower()
                or "hunyuan3d" in node.get("class_type", "").lower()
            )
            for node in workflow.values()
        )
        if is_3d:
            node_type = "ModalRemote3DWorkflow"
        elif video:
            node_type = "ModalRemoteVideoWorkflow"
        else:
            node_type = "ModalRemoteImageWorkflow"
        # A metadata properties.models só existe no grafo formato UI (com
        # pos/properties), não no "prompt" formato API que virou o payload —
        # o ComfyUI manda os dois juntos em extra_pnginfo pra gravação em
        # PNG. Sem ela, o resolvedor cai no chute conservador de sempre
        # ("sdxl") em vez de estimar pelo tamanho real dos pesos.
        ui_workflow = payload.get("extra_data", {}).get("extra_pnginfo", {}).get("workflow")
        models_metadata = extract_models_metadata(ui_workflow) if ui_workflow else []
        payload["prompt"] = {
            "__modal_remote__": {
                "class_type": node_type,
                "inputs": {
                    "workflow_json": json.dumps(workflow),
                    "models_metadata_json": json.dumps(models_metadata),
                },
            }
        }
        payload["extra_data"] = {**payload.get("extra_data", {}), "casa_amarano_dispatch": resolution.as_dict()}
        return payload

    PromptServer.instance.add_on_prompt_handler(on_prompt)


install_prompt_fallback()
