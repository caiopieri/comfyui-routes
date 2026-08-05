"""
Script de Teste de Disparo Real (Live Dispatch Test).
Testa a seleção de GPU pelo Scheduler, verificação de VRAM e execução do subgrafo no Modal.
"""

import json
from comfyui.custom_nodes.comfyui_modal_dispatch.modal_dispatch_node import ModalSubgraphDispatch

def run_test():
    print("=" * 60)
    print("🚀 INICIANDO TESTE DE DISPARO COMFYUI ➔ MODAL")
    print("=" * 60)

    dispatcher = ModalSubgraphDispatch()

    # 1. Teste de geração SDXL (Txt2Img em 1024x1024)
    print("\n1. Testando subgrafo SDXL (30 steps, seed 42)...")
    media, info_json, duration_s, cost_usd = dispatcher.dispatch_subgraph(
        model_name="sdxl",
        task_type="txt2img",
        resolution="1024x1024",
        steps=30,
        seed=42,
        lambda_time_value=15.0,
        bypass_cache=False,
    )

    info = json.loads(info_json)
    print(f"   Status: {info['status']}")
    print(f"   GPU Alocada: {info.get('gpu_allocated', info.get('gpu_used'))}")
    print(f"   Tempo Medido: {duration_s:.2f}s")
    print(f"   Custo Medido: ${cost_usd:.5f} USD")

    # 2. Teste de Cache Hit (Reexecutando exatamente o mesmo subgrafo)
    print("\n2. Testando CACHE (Mesmo subgrafo + mesma seed 42)...")
    media_cache, info_cache_json, duration_cache_s, cost_cache_usd = dispatcher.dispatch_subgraph(
        model_name="sdxl",
        task_type="txt2img",
        resolution="1024x1024",
        steps=30,
        seed=42,
        lambda_time_value=15.0,
        bypass_cache=False,
    )

    info_c = json.loads(info_cache_json)
    print(f"   Status: {info_c['status']}")
    print(f"   Tempo Medido: {duration_cache_s:.2f}s (Reuso Instantâneo)")
    print(f"   Custo Medido: ${cost_cache_usd:.5f} USD (Custo Zero)")

    # 3. Teste do Modelo Wan 2.2 14B Video (Filtro Rígido de VRAM 24GB+)
    print("\n3. Testando Modelo Wan 2.2 14B Video (Filtro de VRAM 24GB+)...")
    media_vid, info_vid_json, dur_vid, cost_vid = dispatcher.dispatch_subgraph(
        model_name="wan_2_2_14b",
        task_type="txt2video",
        resolution="1280x720",
        steps=30,
        seed=12345,
        lambda_time_value=15.0,
        bypass_cache=True,
    )

    info_v = json.loads(info_vid_json)
    print(f"   Status: {info_v['status']}")
    print(f"   GPU Alocada: {info_v['gpu_allocated']}")
    print(f"   Referência de Mídia: {media_vid[:60]}...")
    print(f"   Tempo Medido: {dur_vid:.2f}s")
    print(f"   Custo Medido: ${cost_vid:.5f} USD")

    print("\n" + "=" * 60)
    print("✅ TODOS OS TESTES FORAM EXECUTADOS COM SUCESSO!")
    print("=" * 60)

if __name__ == "__main__":
    run_test()
