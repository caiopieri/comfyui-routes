# Operação e produção

## O que pode ser publicado agora

O worker ComfyUI/Modal existente continua sendo o caminho operacional atual:

```bash
modal setup
modal deploy comfyui/modal_backend/app.py
```

Modelos são persistidos no volume `comfyui-models-vol`. O deploy precisa ser
feito depois de autenticar o CLI e confirmar que o volume contém os pesos
correspondentes ao workflow.

O núcleo novo pode ser instalado como pacote local:

```bash
python -m pip install -e .
```

## Critério de produção do orquestrador

O orquestrador só deve receber tráfego real depois que a matriz Wan 2.2 tiver
benchmarks cold/warm reais para os targets publicados. Sem isso, o planner
retorna `SchedulingError` deliberadamente; essa é uma proteção contra
decisões baseadas em números inventados.

## Checklist do primeiro deploy

- [ ] credenciais Modal disponíveis no ambiente de deploy;
- [ ] volume e pesos confirmados;
- [ ] pipeline e versão fixados;
- [ ] targets e topologias registradas;
- [ ] cold/warm benchmarks persistidos;
- [ ] p95 e custo revisados;
- [ ] fallback testado;
- [ ] telemetry e backup do SQLite configurados;
- [ ] smoke test remoto concluído.

O deploy do worker atual e o deploy do scheduler novo são etapas distintas:
o primeiro fornece compute; o segundo só fica autorizado após a evidência do
benchmark e a definição do alvo de produção.
