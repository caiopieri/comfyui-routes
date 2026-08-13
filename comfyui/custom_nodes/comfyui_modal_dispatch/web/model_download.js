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

async function baixarModelosFaltantes() {
  const modelos = modelosDoWorkflowAtual();
  if (modelos.length === 0) {
    alert(
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
  const confirmado = confirm(
    `${comTamanho.length} modelo(s) referenciado(s) no workflow:\n\n${linhas}\n\n` +
      `Total estimado: ${formatarTamanho(totalBytes)} no Volume do Modal.\n\n` +
      `Confirmar download pro Modal?`
  );
  if (!confirmado) return;

  const downloadResp = await fetch("/casa_amarano/download_models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ models: comTamanho }),
  });
  const { job_id } = await downloadResp.json();
  alert(
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
      alert("Download concluído! Os modelos já estão no Volume do Modal.");
      return;
    }
    if (status.status === "error") {
      alert(`Download falhou: ${status.error || "erro desconhecido"}`);
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
