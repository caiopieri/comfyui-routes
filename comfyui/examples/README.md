# Exemplos de workflow — Casa Amarano

Guia rápido pra quem está aprendendo ComfyUI. Todos os arquivos abaixo são
carregáveis direto no ComfyUI local (`comfyui/start.sh`): arraste o `.json`
para a janela do navegador, ou use *Workflow → Open*.

## `workflow_sdxl_local_leve_modal_pesado.json` (comece por este)

Um grafo SDXL **normal** — não tem nenhum nó especial de dispatcher visível.
Nós locais (baratos, não precisam de GPU):

| Nó | O que faz |
|---|---|
| `CheckpointLoaderSimple` | referencia o checkpoint `sd_xl_base_1.0.safetensors` (não existe no seu Mac — só no Volume do Modal) |
| `CLIPTextEncode` × 2 | prompt positivo e negativo, em texto puro |
| `EmptyLatentImage` | parâmetros de resolução (1024×1024) |
| `KSampler` | parâmetros de amostragem (seed, steps, cfg, sampler) — **é aqui que o trabalho pesado de GPU acontece** |
| `VAEDecode` | decodifica o latente em imagem |
| `PreviewImage` / `SaveImage` | mostra e salva o resultado |

Quando você aperta *Queue Prompt*, o `custom_nodes/comfyui_modal_dispatch`
(carregado automaticamente pelo `start.sh`) detecta que o checkpoint SDXL
não está no seu Mac, troca o workflow inteiro por um único nó remoto
(`ModalRemoteImageWorkflow`) **antes de qualquer validação local**, dispara
ele no Modal, e devolve a imagem pro `PreviewImage`/`SaveImage` como se
tivesse rodado localmente. Você não precisa saber que isso aconteceu —
é a interceptação transparente em `remote_workflow_node.py::install_prompt_fallback`.

Não precisa mexer em `subgraph_json_override` nem adicionar nenhum nó do
Modal manualmente: monte o grafo normal, o dispatch acontece sozinho.

## `workflow_modal_dispatch_example.json`

Teste de fumaça: só o nó `ModalSubgraphDispatch` isolado + um `PreviewImage`.
Serve pra verificar que o nó customizado carrega e dispara no Modal, mas
não representa um workflow real de produção (não tem prompt separado por
nó, não tem `SaveImage`). Use o de cima como referência de workflow de
verdade.

## `workflow_sdxl_api_remote.json`

O mesmo grafo do primeiro exemplo, mas em **formato API** (o JSON que o
ComfyUI exporta com *Save (API Format)*, não o formato de UI com posições
de nó). É o que os scripts do `modal_backend/` (`dispatch_workflow.py`,
`run_workflow.py`) esperam receber via `--workflow-file`. Use este formato
se for disparar workflows por linha de comando em vez de pela UI.
