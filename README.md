# Adaptive Inference Orchestrator

Benchmark-backed orchestration for AI inference workloads.

O projeto está evoluindo de uma integração ComfyUI + Modal para um
**Stateful Adaptive Inference Orchestrator**: o cliente descreve o workload e
seu SLA; o sistema compara targets de execução usando dados medidos, escolhe
um plano e registra a diferença entre previsão e realidade.

```text
request → workload normalizer → benchmark predictor → SLA planner
        → provider/worker → result + telemetry → knowledge base
```

## Estado atual

O primeiro vertical slice do MVP já está em `src/adaptive_inference`:

- contratos para workload, SLA, target, worker, plano e telemetria;
- Benchmark Harness reproduzível com runs `cold` e `warm`;
- persistência SQLite de amostras, estado de workers e telemetry;
- percentis `p50`, `p90`, `p95` e `p99`;
- predictor baseado exclusivamente em benchmarks bem-sucedidos;
- planner com políticas `economy`, `balanced`, `fast` e `frontier`;
- filtros de `max_latency`, `max_queue_delay`, `max_cost` e `min_quality`;
- feedback loop prediction-versus-actual;
- adapter para o worker ComfyUI já existente no Modal.

O protocolo inicial é orientado ao caso Wan 2.2, mas não contém números
inventados: um target só entra no plano depois de possuir benchmarks para a
combinação exata de modelo, versão, pipeline, quantização, resolução, frames
e steps.

## Começando

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python -m unittest discover -s comfyui/tests -p 'test_*.py'
```

Consultar uma knowledge base:

```bash
adaptive-inference summary \
  --db ~/.adaptive_inference.db \
  --workload-key 'wan22-t2v-720p-81f:<digest>' \
  --target-id modal-h100-1 \
  --run-kind warm
```

Calcular um plano a partir dos exemplos:

```bash
adaptive-inference plan \
  --db ~/.adaptive_inference.db \
  --request examples/adaptive/request.json \
  --targets examples/adaptive/targets.json
```

O uso programático do harness e o contrato que um provider precisa
implementar estão em [docs/benchmarking.md](docs/benchmarking.md).

## Estrutura

```text
src/adaptive_inference/       núcleo provider-agnostic do orquestrador
  models.py                   contratos de domínio
  storage.py                  knowledge base SQLite + runtime state
  benchmark.py                protocolo cold/warm e coleta de amostras
  predictor.py                previsão p50/p95/custo/confiança
  scheduler.py                planejamento SLA-aware
  execution.py                execução + telemetry feedback loop
  providers/                  fronteiras de execução e adapter Modal
tests/                        testes do novo núcleo
comfyui/                      integração legada ComfyUI/Modal preservada
docs/                         arquitetura, benchmark, operação e roadmap
examples/adaptive/            request e targets de demonstração
```

## ComfyUI + Modal existente

A integração atual continua disponível: ela roda o ComfyUI local em CPU,
detecta modelos ausentes, despacha o workflow para workers no Modal e devolve
os outputs. O setup operacional está em
[docs/comfyui_modal_setup.md](docs/comfyui_modal_setup.md).

O novo núcleo não substitui esse caminho de forma implícita. Ele define a
camada de decisão que será conectada ao executor Wan benchmarkado na próxima
fase. Assim, o scheduler não transforma um chute em uma falsa medição.

## Roadmap

1. Benchmark Harness e knowledge base — implementado.
2. Predictor + execution plan — implementado.
3. Runtime state e warm reuse — contrato e planner implementados; coleta em produção em andamento.
4. Wan 2.2 benchmarkado em Modal — próximo marco operacional.
5. Filas, fairness, micro-batching e autoscaling.
6. Providers adicionais: fal, RunPod, infraestrutura própria e APIs comerciais.
7. Quality-aware routing e políticas de produto.

Detalhes e decisões estão em [docs/architecture.md](docs/architecture.md) e
[docs/roadmap.md](docs/roadmap.md).
