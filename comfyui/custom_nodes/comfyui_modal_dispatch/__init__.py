"""
Registro de Nós Customizados do ComfyUI Modal Dispatcher.
"""

from .modal_dispatch_node import ModalSubgraphDispatch
from .remote_workflow_node import ModalRemoteImageWorkflow, ModalRemoteVideoWorkflow, ModalRemote3DWorkflow
from . import model_download_routes  # noqa: F401 — registra as rotas /casa_amarano/* ao importar

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "ModalSubgraphDispatch": ModalSubgraphDispatch,
    "ModalRemoteImageWorkflow": ModalRemoteImageWorkflow,
    "ModalRemoteVideoWorkflow": ModalRemoteVideoWorkflow,
    "ModalRemote3DWorkflow": ModalRemote3DWorkflow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ModalSubgraphDispatch": "🚀 Modal Subgraph Dispatcher (Casa Amarano)",
    "ModalRemoteImageWorkflow": "Modal Remote Image (automatic)",
    "ModalRemoteVideoWorkflow": "Modal Remote Video (automatic)",
    "ModalRemote3DWorkflow": "Modal Remote 3D (automatic)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
