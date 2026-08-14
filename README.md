# ComfyUI Local + Dispatcher Modal + GPU Scheduler — Casa Amarano

> **Guia Oficial de Operação & Arquitetura (PRD 09)**  
> Este repositório contém o ambiente de trabalho ComfyUI do projeto Casa Amarano, projetado para iteração rápida e custo otimizado sem necessidade de GPU local.

---

## 💡 Princípio de Funcionamento

1. **Interface Local Leve (Custo R$ 0)**: O Caio roda o ComfyUI na máquina dele (macOS, Windows ou Linux). Ele monta workflows, edita prompts, testa nós leves e navega pela interface sem gastar nada de GPU.
2. **Despacho por Subgrafo**: Apenas a etapa pesada de amostragem/geração (ex: KSampler + VAE Decode / Wan 2.2) é empacotada pelo nó customizado `Modal Subgraph Dispatcher` e enviada para o **Modal**.
3. **Roteamento Inteligente de GPU**: O Scheduler escolhe a melhor GPU (T4, L4, A10G, A100 ou H100) combinando:
   - **Filtro Rígido de VRAM**: Elimina GPUs onde o modelo não cabe. Wan 2.2 14B fica restrito a GPUs de 80 GB neste catálogo, conforme o requisito oficial do projeto.
   - **Histórico Medido no SQLite**: Aprende o tempo real de cada GPU com os dados de execuções anteriores.
   - **Cálculo de Score**: $\text{custo} = \text{preco\_segundo} \times (\text{tempo\_estimado} + \text{cold\_start})$, $\text{score} = \text{custo} + \lambda \times (\text{tempo\_total} / 3600)$.
   - **Containers Quentes**: Se o container já estiver ativo no Modal, $\text{cold\_start} = 0$, reduzindo o tempo total e alterando a escolha da GPU.
4. **Cache por Seed + Parâmetros**: Reexecutar o mesmo subgrafo com a mesma seed retorna o resultado instantaneamente do cache SQLite a Custo Zero ($0.00).

---

## 🛠️ Instalação Passo a Passo

### Opção recomendada no Mac Intel: Docker

O Mac roda apenas a interface; a geração continua no Modal. O container usa o
checkout atual do ComfyUI e wheels Linux CPU, sem depender do Python Intel do
macOS:

```bash
cd ~/Projetos/Casa\ Amarano
docker compose -f compose.comfyui.yaml up -d --build
```

Abra `http://127.0.0.1:8188`. Para parar:

```bash
docker compose -f compose.comfyui.yaml down
```

### 1. Pré-requisitos
- macOS Intel com `/usr/local/bin/python3.12`.
- Conta no [Modal.com](https://modal.com) criada.
- CLI do Modal instalada e autenticada:
  ```bash
  pip install modal
  modal setup
  ```

### 2. Instalar o ComfyUI Local

#### No macOS Intel:
```bash
cd ~/ComfyUI/ComfyUI
rm -r venv
/usr/local/bin/python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python --version  # 3.12.x
```

#### No Windows:
Use o instalador portátil do ComfyUI (*ComfyUI Portable*) ou clone o repositório e execute em um ambiente Python (`venv`).

### 3. Instalar o Custom Node no ComfyUI Local

Copie a pasta `comfyui/custom_nodes/comfyui_modal_dispatch` para a pasta `custom_nodes/` da sua instalação do ComfyUI:

```bash
ln -s "$HOME/Projetos/Casa Amarano/comfyui/custom_nodes/comfyui_modal_dispatch" \
  "$HOME/ComfyUI/ComfyUI/custom_nodes/comfyui_modal_dispatch"
```

Reinicie o ComfyUI local:
```bash
~/Projetos/Casa\ Amarano/comfyui/start.sh
```

No menu de nós do ComfyUI, você verá o novo nó em:  
`Casa Amarano / Modal` ➔ `🚀 Modal Subgraph Dispatcher (Casa Amarano)`

---

## 🚀 Como Usar no ComfyUI

1. Adicione o nó **`🚀 Modal Subgraph Dispatcher`** no seu canvas.
2. Configure os parâmetros de iteração:
   - **`model_name`**: perfil da família desejada. O catálogo inclui SD 1.5/XL, FLUX 1/2, Wan 2.1/2.2, HunyuanVideo, CogVideoX, LTX-Video, Mochi e upscale.
   - **`task_type`**: `txt2img`, `img2img`, `txt2video` ou `img2video`.
   - **`resolution`**: `1024x1024`, `1280x720`, etc.
   - **`steps`**: Número de passos (ex: 30).
   - **`seed`**: Semente aleatória ou fixa.
   - **`lambda_time_value` ($\lambda$)**: Ajusta a prioridade entre Custo e Tempo.
3. Conecte as saídas do nó aos visualizadores (`PreviewImage` ou exibidore de texto para vídeos).
4. Clique em **Queue Prompt**. A barra de progresso do ComfyUI refletirá o andamento em tempo real do Modal!

---

## ⚙️ Ajustando o Parâmetro $\lambda$ (Valor da Hora)

O parâmetro $\lambda$ representa quanto vale **1 hora do tempo do Caio em dólares** ($\text{USD/h}$):

- **$\lambda = 0$ (Modo Lote Noturno / Economia Máxima)**:  
  O Scheduler ignora o tempo de espera e escolhe estritamente a GPU mais barata (ex.: L4 ou T4).
- **$\lambda = 15$ (Padrão de Iteração Diária - R$ 75-80/h)**:  
  Equilíbrio saudável entre custo e velocidade.
- **$\lambda = 50+$ (Modo "Quero Ver Agora" / Alta Velocidade)**:  
  O Scheduler dá preferência a GPUs ultra-rápidas (A100 / H100) para entregar o resultado em poucos segundos.

---

## 💰 Teto Mensal de Gastos & Proteção de Custos

O sistema possui um teto mensal automático configurado em **$50,00 USD** (editável via variável de ambiente `COMFY_MONTHLY_BUDGET_CAP`).

Se o teto for atingido no mês vigente:
- O nó customizado interrompe a execução com um alerta visual claro.
- Nenhuma chamada nova é enviada ao Modal até a virada do mês ou reajuste manual da variável.

---

## 📊 Medição e Tabela de Custos Reais

Os custos são **medidos empiricamente** e salvos no banco SQLite `~/.comfy_scheduler.db`.

| Modelo / Tarefa | GPU Alocada | Cold Start | Tempo de Execução | Custo Real Medido |
|-----------------|-------------|------------|-------------------|-------------------|
| Execução | GPU | Cold Start | Tempo | Custo real |
|---|---|---:|---:|---:|
| Ainda não medido | — | — | — | — |

> Não declarar custo real até uma geração remota concluída e confirmada no Modal.

### Catálogo e estado de execução

O catálogo em `comfyui/modal_backend/config.py` configura o limite de VRAM e a
matriz de GPUs para cada família. Ele não baixa automaticamente todos os
checkpoints: os pesos podem ocupar dezenas de GB, exigir aceite de licença ou
token do Hugging Face.

Neste momento, o caminho de geração real validado pelo ComfyUI é `sdxl`. Os
demais perfis já participam do filtro e dos testes do scheduler, mas o nó os
recusa com mensagem explícita até existir um executor Modal específico e os
pesos correspondentes no Volume. Isso evita gerar SDXL ou um placeholder
acreditando que foi Wan, FLUX ou Hunyuan.

Referências usadas para os limites mais sensíveis: [Wan 2.2](https://github.com/Wan-Video/Wan2.2), [HunyuanVideo](https://github.com/Tencent-Hunyuan/HunyuanVideo), [HunyuanVideo 1.5](https://github.com/Tencent-Hunyuan/HunyuanVideo-1.5), [FLUX.2](https://github.com/black-forest-labs/flux2).

Para preparar o workflow LTX-2.3 I2V da comunidade, os modelos já podem ser
baixados diretamente para o Volume Modal com:

```bash
modal run comfyui/modal_backend/download_models.py --preset ltx-2.3-i2v
```

Esse preset ocupa aproximadamente 40 GB e usa A100-40GB como limite mínimo do
scheduler; A100-80GB ou H100 são opções mais seguras para vídeos maiores.

---

## 🧪 Testes Automatizados

Para rodar os testes unitários do Scheduler de GPU:

```bash
python3 -m unittest comfyui/tests/test_router.py
```
## Execução automática local → Modal

O ComfyUI local roda a interface em CPU. Ao clicar em **Executar**, o nó
customizado inspeciona o workflow API antes da validação local. Se um arquivo
de modelo referenciado não existir em `models/`, o workflow inteiro é enviado
ao Modal; o roteador escolhe a GPU conforme o perfil do modelo, VRAM, lambda e
histórico de cold start. Imagens de `LoadImage` são transferidas junto com a
requisição e os arquivos de saída retornam para a pasta `output/` do ComfyUI.

Isso permite carregar um workflow comunitário compatível, como LTX-2.3, e
clicar em **Executar** sem baixar os pesos para o Mac. O workflow precisa estar
no formato API aceito pelo ComfyUI e seus nós customizados precisam existir no
container local; apenas os pesos são resolvidos automaticamente.

Se o modelo já existir localmente, o ComfyUI segue o caminho local normal.
