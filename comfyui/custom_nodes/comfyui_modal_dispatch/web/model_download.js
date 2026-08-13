import { app } from "../../../scripts/app.js";

function extrairModelos(node, achados, vistos) {
  if (Array.isArray(node)) {
    for (const item of node) extrairModelos(item, achados, vistos);
    return;
  }
  if (node && typeof node === "object") {
    const modelos = node.properties && node.properties.models;
    if (Array.isArray(modelos)) {
      for (const m of modelos) {
        if (m && m.name && m.url && !vistos.has(m.name)) {
          vistos.add(m.name);
          achados.push(m);
        }
      }
    }
    for (const valor of Object.values(node)) extrairModelos(valor, achados, vistos);
  }
}

function modelosDoWorkflowAtual() {
  const grafo = app.graph.serialize();
  const achados = [];
  extrairModelos(grafo, achados, new Set());
  return achados;
}

function formatarTamanho(bytes) {
  if (!bytes) return "tamanho desconhecido";
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

// Diálogos próprios, sem confirm()/alert() nativos — esses travam a aba
// inteira esperando clique, o que é ruim de UX e quebra qualquer automação
// de teste na página. Overlay simples via DOM, sem depender de APIs
// internas do ComfyUI (mais robusto entre versões).
function estiloOverlay() {
  return "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:99999;" +
    "display:flex;align-items:center;justify-content:center;font-family:sans-serif;";
}

function estiloCaixa() {
  return "background:#1e1e1e;color:#eee;border-radius:8px;padding:20px;" +
    "max-width:520px;width:90%;box-shadow:0 8px 30px rgba(0,0,0,0.5);" +
    "white-space:pre-wrap;font-size:13px;line-height:1.5;";
}

function estiloBotao(cor) {
  return `background:${cor};color:#fff;border:none;border-radius:4px;` +
    "padding:8px 16px;margin-top:14px;margin-right:8px;cursor:pointer;font-size:13px;";
}

function mostrarConfirmacao(texto) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.style.cssText = estiloOverlay();
    const caixa = document.createElement("div");
    caixa.style.cssText = estiloCaixa();
    caixa.textContent = texto;

    const botoes = document.createElement("div");
    const confirmar = document.createElement("button");
    confirmar.textContent = "Confirmar download pro Modal";
    confirmar.style.cssText = estiloBotao("#2d7d46");
    const cancelar = document.createElement("button");
    cancelar.textContent = "Cancelar";
    cancelar.style.cssText = estiloBotao("#555");

    const fechar = (resultado) => {
      document.body.removeChild(overlay);
      resolve(resultado);
    };
    confirmar.onclick = () => fechar(true);
    cancelar.onclick = () => fechar(false);

    botoes.appendChild(confirmar);
    botoes.appendChild(cancelar);
    caixa.appendChild(botoes);
    overlay.appendChild(caixa);
    document.body.appendChild(overlay);
  });
}

function mostrarAviso(texto) {
  const overlay = document.createElement("div");
  overlay.style.cssText = estiloOverlay();
  const caixa = document.createElement("div");
  caixa.style.cssText = estiloCaixa();
  caixa.textContent = texto;

  const fechar = document.createElement("button");
  fechar.textContent = "OK";
  fechar.style.cssText = estiloBotao("#2d6ca2");
  fechar.onclick = () => document.body.removeChild(overlay);

  caixa.appendChild(fechar);
  overlay.appendChild(caixa);
  document.body.appendChild(overlay);
}

async function baixarModelosFaltantes() {
  const modelos = modelosDoWorkflowAtual();
  if (modelos.length === 0) {
    mostrarAviso(
      "Esse workflow não tem metadata de modelo (properties.models) — normal em " +
        "workflows sem essa informação embutida. Não dá pra descobrir a URL sozinho."
    );
    return;
  }

  const infoResp = await fetch("/casa_amarano/missing_models_info", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ models: modelos }),
  });
  const { models: comTamanho } = await infoResp.json();

  const totalBytes = comTamanho.reduce((acc, m) => acc + (m.size_bytes || 0), 0);
  const linhas = comTamanho
    .map((m) => `  - ${m.name} (${formatarTamanho(m.size_bytes)}) -> ${m.directory}`)
    .join("\n");
  const confirmado = await mostrarConfirmacao(
    `${comTamanho.length} modelo(s) referenciado(s) no workflow:\n\n${linhas}\n\n` +
      `Total estimado: ${formatarTamanho(totalBytes)} no Volume do Modal.`
  );
  if (!confirmado) return;

  const downloadResp = await fetch("/casa_amarano/download_models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ models: comTamanho }),
  });
  const { job_id } = await downloadResp.json();
  mostrarAviso(
    "Download iniciado em segundo plano no Modal. Pode continuar usando o " +
      "ComfyUI normalmente — quando terminar, é só clicar em Executar de novo."
  );

  const deadline = Date.now() + 60 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 15000));
    const statusResp = await fetch(`/casa_amarano/download_models/${job_id}`);
    if (!statusResp.ok) break;
    const status = await statusResp.json();
    if (status.status === "done") {
      mostrarAviso("Download concluído! Os modelos já estão no Volume do Modal.");
      return;
    }
    if (status.status === "error") {
      mostrarAviso(`Download falhou: ${status.error || "erro desconhecido"}`);
      return;
    }
  }
}

app.registerExtension({
  name: "CasaAmarano.ModalMissingModels",
  commands: [
    {
      id: "casaAmarano.baixarModelosFaltantes",
      label: "Casa Amarano: Baixar modelos faltantes pro Modal",
      function: baixarModelosFaltantes,
    },
  ],
  menuCommands: [
    {
      path: ["Extensions"],
      commands: ["casaAmarano.baixarModelosFaltantes"],
    },
  ],
});
