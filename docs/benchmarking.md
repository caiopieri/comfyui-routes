# Benchmark Harness

O benchmark é a fonte de verdade do planner. Heurísticas podem ordenar dados
existentes, mas não criam uma performance presumida para uma combinação que
nunca foi medida.

## Protocolo

Para cada `WorkloadSpec` e `ExecutionTarget`, o harness executa:

- pelo menos uma run `cold` em uma sessão sem modelo aquecido;
- pelo menos cinco runs `warm` na mesma sessão;
- sempre os mesmos parâmetros de workload em todos os targets;
- persistência da amostra mesmo quando uma run falha.

`total_s` representa o tempo observado daquela execução. Em uma cold run ele
inclui startup/model load; em warm run ele representa a inferência com o
worker já preparado. Isso evita contar cold start duas vezes no predictor.

## Métricas

O registro suporta:

`model`, `model_version`, `pipeline`, `pipeline_version`, `quantization`,
resolução, frames, steps, GPU, GPU count, interconnect, provider, cold start,
model load, warm inference, total, VRAM máxima, throughput, preço e custo real.

O store calcula `p50`, `p90`, `p95`, `p99`, média, custo p50/p95 e taxa de
sucesso a partir das amostras bem-sucedidas. As falhas permanecem no banco
para análise de confiabilidade.

## Implementando um adapter

O provider só precisa implementar o protocolo abaixo:

```python
from adaptive_inference.benchmark import AdapterObservation, BenchmarkHarness

class WanAdapter:
    def execute(self, workload, target, run_kind, run_index):
        # run_kind="cold" deve criar/selecionar sessão fria;
        # run_kind="warm" deve reutilizar a sessão aquecida.
        metrics = run_wan(workload, target, cold=(run_kind == "cold"))
        return AdapterObservation(
            total_s=metrics.total_s,
            model_load_s=metrics.model_load_s,
            inference_s=metrics.inference_s,
            max_vram_gb=metrics.max_vram_gb,
            throughput=metrics.frames / metrics.inference_s,
            actual_cost_usd=metrics.cost_usd,
        )

harness = BenchmarkHarness(store)
result = harness.run(workload, target, WanAdapter())
print(result.warm_summary.p95_latency_s)
```

O adapter é responsável por garantir a semântica cold/warm do provider; o
harness é responsável pela repetição, relógio, persistência e agregação.

## Ordem do benchmark Wan 2.2

O primeiro experimento de produção deve fixar uma matriz explícita, por
exemplo:

```text
Wan 2.2 A14B
pipeline escolhido e versão fixada
FP8
1280×720
81 frames
steps fixos
RTX PRO 6000 / H100 / H200 / B200
1×, 2×, 4×, 8× quando suportado pelo pipeline
```

O resultado deve ser revisado antes de ser usado no scheduler. Se um target
falhar por OOM ou indisponibilidade, essa falha deve ser registrada, não
substituída por um número estimado.
