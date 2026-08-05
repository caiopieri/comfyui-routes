"""
Registro de Nós Customizados do ComfyUI Modal Dispatcher.
"""

from .modal_dispatch_node import ModalSubgraphDispatch
from .remote_workflow_node import ModalRemoteImageWorkflow, ModalRemoteVideoWorkflow

NODE_CLASS_MAPPINGS = {
    "ModalSubgraphDispatch": ModalSubgraphDispatch,
    "ModalRemoteImageWorkflow": ModalRemoteImageWorkflow,
    "ModalRemoteVideoWorkflow": ModalRemoteVideoWorkflow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ModalSubgraphDispatch": "🚀 Modal Subgraph Dispatcher (Casa Amarano)",
    "ModalRemoteImageWorkflow": "Modal Remote Image (automatic)",
    "ModalRemoteVideoWorkflow": "Modal Remote Video (automatic)",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
