# Arquitetura do Adaptive Inference Orchestrator

## Decisão central

O sistema escolhe entre estratégias de infraestrutura previamente
benchmarkadas. Ele não inventa uma nova técnica de inferência durante uma
request e não altera silenciosamente pipeline, quantização ou parâmetros do
workload.

Uma alternativa é um `ExecutionTarget`: provider, GPU, quantidade de GPUs,
topologia, região, preço, startup esperado e score de qualidade. O target só
é comparado quando há dados para a chave exata do workload.

## Fluxo

```text
                 ┌─────────────────────┐
                 │ InferenceRequest    │
                 │ workload + SLA      │
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐
                 │ BenchmarkPredictor  │◄──── BenchmarkStore
                 └──────────┬──────────┘      (raw samples)
                            │                  ▲
                            ▼                  │
                 ┌─────────────────────┐      │
                 │ AdaptiveScheduler   │◄──── RuntimeWorker state
                 └──────────┬──────────┘
                            ▼
                 ┌─────────────────────┐
                 │ ExecutionProvider   │
                 │ Modal/fal/RunPod/...│
                 └──────────┬──────────┘
                            ▼
                 result + actual metrics ───► telemetry
```

## Contratos

### WorkloadSpec

Contém `model`, `model_version`, `pipeline`, `pipeline_version`,
`quantization`, resolução, frames e steps. Seu `workload_key` é um hash
determinístico de todos esses campos, impedindo que um benchmark de 720p seja
reutilizado para 1080p ou para outra revisão do pipeline.

### SLA

Pode impor `max_latency_s`, `max_queue_delay_s`, `max_cost_usd` e
`min_quality`. `latency_target_s`, `priority` e `mode` expressam preferência.
No MVP, a prioridade já pertence ao contrato; aging/fairness da fila entra na
fase de queueing.

### RuntimeWorker

Modela `COLD`, `STARTING`, `LOADING_MODEL`, `WARM_IDLE`, `BUSY`, `DRAINING` e
`TERMINATING`, além de workload carregado, atraso da fila, profundidade,
VRAM disponível e confiabilidade. Um worker `BUSY` compatível pode vencer um
worker novo se o benchmark warm mais sua fila respeitar o SLA.

### BenchmarkSample

Uma amostra guarda cold start/model load, inferência warm, total, VRAM,
throughput e custo real. O harness mantém runs cold e warm separadas.

## Planner

O planner:

1. elimina targets desabilitados ou incompatíveis;
2. exige benchmark para cold ou warm conforme o estado do worker;
3. calcula p50, p95, custo e confiança;
4. aplica limites rígidos do SLA;
5. ranqueia os sobreviventes segundo `economy`, `balanced`, `fast` ou `frontier`;
6. devolve o target, worker, score e explicação da previsão.

Para latência, o filtro usa p95, não a média. O score usa p95 como sinal de
risco e p50/custo como eficiência. O `safety_margin_s` pode ser configurado
quando os dados ainda forem poucos.

## Persistência

O SQLite guarda amostras brutas, snapshots de workers e telemetry. Summaries
são calculados sob demanda; isso permite mudar a política de percentis sem
migrar ou perder dados históricos.

## Limites conscientes do MVP

- ainda não existe uma fila distribuída nem lease transacional de worker;
- fairness/aging e micro-batching ainda são fases seguintes;
- quality score é metadata benchmarkada, não avaliação automática de vídeo;
- o adapter Modal usa o executor ComfyUI atual, que ainda não é o executor
  nativo benchmarkado de Wan 2.2 multi-GPU;
- novos providers entram por adapters e targets, sem alterar o planner.
