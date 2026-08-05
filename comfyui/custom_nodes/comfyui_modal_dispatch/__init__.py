"""
Registro de Nós Customizados do ComfyUI Modal Dispatcher.
"""

from comfyui.custom_nodes.comfyui_modal_dispatch.modal_dispatch_node import ModalSubgraphDispatch

NODE_CLASS_MAPPINGS = {
    "ModalSubgraphDispatch": ModalSubgraphDispatch
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ModalSubgraphDispatch": "🚀 Modal Subgraph Dispatcher (Casa Amarano)"
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
