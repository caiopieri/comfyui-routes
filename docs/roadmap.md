# Roadmap de entrega

## Fase 1 — Evidence layer (entregue nesta branch)

- contratos estáveis de workload, target, SLA e worker;
- harness cold/warm reproduzível;
- SQLite com amostras brutas, percentis e telemetry;
- planner que para quando não existe evidência suficiente;
- testes unitários sem dependências externas.

## Fase 2 — Primeiro workload de produção

- fixar o pipeline Wan 2.2 A14B;
- criar adapter de execução que coleta VRAM e custo real;
- medir Modal nas topologias disponíveis;
- validar qualidade e outputs;
- publicar a primeira matriz assinada/versionada de benchmarks.

## Fase 3 — Estado vivo e execução

- heartbeat dos workers;
- leases para impedir dupla alocação;
- atualização de `COLD` a `TERMINATING`;
- integração do planner ao executor Modal;
- telemetry automática prediction-versus-actual.

## Fase 4 — Scheduling de tráfego

- fila por prioridade com aging;
- deadlines e fairness;
- janela dinâmica de micro-batching;
- autoscaling baseado em fila, SLA e probabilidade de demanda.

## Fase 5 — Providers e qualidade

- fal e RunPod;
- APIs comerciais como execution targets;
- fallback/replanning por timeout e indisponibilidade;
- quality-aware routing e modos de produto.
