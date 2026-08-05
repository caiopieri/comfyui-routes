# Especificação Técnica e Guia de Setup — ComfyUI & Modal (PRD 09)

> **Documentação de Infraestrutura do Projeto Casa Amarano**  
> Data: 2026-08-05

---

## 1. Visão de Arquitetura

O ecossistema ComfyUI da Casa Amarano divide **Controle (local)** de **Músculo (Modal GPU)**:

```
┌─────────────────────────────────────────┐          ┌─────────────────────────────────────────┐
│        Computador do Caio (Local)        │          │              Modal Serverless           │
│                                         │          │                                         │
│ ┌─────────────────────────────────────┐ │  HTTPS   │ ┌─────────────────────────────────────┐ │
│ │ UI ComfyUI + Nó Subgraph Dispatcher │ │─────────►│ │ Backend Headless ComfyUI            │ │
│ └─────────────────────────────────────┘ │          │ └─────────────────────────────────────┘ │
│                   │                     │          │                    │                    │
│ ┌─────────────────▼───────────────────┐ │          │ ┌──────────────────▼──────────────────┐ │
│ │ GPURouter & DB SQLite (~/.db)       │ │          │ │ modal.Volume (/models)                │ │
│ └─────────────────────────────────────┘ │          │ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘          └─────────────────────────────────────────┘
```

### Regras Principais:
1. **Zero GPU Local**: Nenhum modelo pesado é carregado localmente.
2. **Subgrafos Estagiados**: O nó envia um estágio inteiro do pipeline para o Modal em uma única requisição HTTP/gRPC.
3. **Mídias Leves vs Pesadas**:
   - Imagens pequenas/médias transitam via Base64/PNG no JSON da API.
   - Vídeos gerados são gravados diretamente no `modal.Volume` e retornados via referência/URL de streaming.
4. **Isolamento de Segurança**: O backend roda em ambiente isolado no Modal sem acesso a segredos da rede doméstica.

---

## 2. Configuração do Ambiente Modal

### Instalar a CLI do Modal
```bash
pip install modal
```

### Autenticar a Máquina
```bash
modal setup
```
Isso abrirá o navegador para vincular sua conta do Modal e salvar o token de acesso em `~/.modal.toml`.

### Subir o App Backend para Produção no Modal
Para implantar a aplicação de worker ComfyUI no Modal:

```bash
cd "/Users/caioamaraldepieri/Projetos/Casa Amarano"
modal deploy comfyui/modal_backend/app.py
```

### Upload Inicial de Modelos para o `modal.Volume`
Os checkpoints (ex: SDXL, FLUX, Wan 2.2) devem ser armazenados no Volume persistente `comfyui-models-vol`:

```bash
# Criar diretórios no volume
modal volume create comfyui-models-vol

# Enviar modelo checkpoint para o volume
modal volume put comfyui-models-vol /caminho/local/modelo.safetensors /checkpoints/modelo.safetensors
```

---

## 3. Estrutura do Banco SQLite (`~/.comfy_scheduler.db`)

O banco SQLite armazena o histórico real de medição e a tabela de cache.

### Tabela `executions`
- `job_id`: ID único da execução
- `task_type`: Tipo de tarefa (`txt2img`, `txt2video`, etc)
- `model`: Nome do modelo
- `gpu`: GPU utilizada (`T4`, `L4`, `A10G`, `A100-40GB`, `A100-80GB`, `H100`)
- `resolution`: Resolução da mídia
- `steps`: Quantidade de passos de amostragem
- `duration_s`: Tempo medido de execução
- `cost_usd`: Custo real cobrado em USD
- `warm_container`: 1 se container estava quente, 0 se frio
- `seed`: Semente utilizada
- `timestamp`: Epoch time da execução

---

## 4. Solução de Problemas (Troubleshooting)

### Erro: `BudgetExceededException`
- **Causa**: O gasto mensal acumulado ultrapassou o teto definido (padrão: $50,00 USD).
- **Solução**: Aguarde a virada do mês ou aumente temporariamente a variável de ambiente:
  ```bash
  export COMFY_MONTHLY_BUDGET_CAP=75.0
  ```

### Erro: `ValueError: Nenhuma GPU atende ao requisito de VRAM mínima`
- **Causa**: O modelo selecionado (ex: Wan 2.2 14B) exige mais VRAM do que as GPUs menores comportam.
- **Solução**: O Scheduler selecionará automaticamente GPUs de 24GB+ (L4, A10G, A100, H100).

### Desempenho Lento no Primeiro Disparo (Cold Start)
- **Causa**: Inicialização da imagem Linux e carregamento dos pesos da GPU no Modal.
- **Solução**: O container permanece **quente por 5 minutos** (`container_idle_timeout=300`). Os disparos seguintes durante a iteração ocorrerão em tempo recorde sem custo de cold start.
