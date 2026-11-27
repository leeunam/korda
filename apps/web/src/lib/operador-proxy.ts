const IDs = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const ACOES = new Set(["importar", "decidir-plano", "executar", "decidir-entrega", "promover"]);
const ARQUIVOS = new Set(["pacote.zip", "kpis.json", "por_pedido.csv", "por_viagem.csv"]);
const LOCAIS = new Set(["localhost", "127.0.0.1", "[::1]"]);

function erro(error: string, status: number) {
  return Response.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
}

function alvo(metodo: string, rota: string[], busca: URLSearchParams) {
  const [prefixo, projeto, acao, run, arquivos, nome] = rota;
  if (prefixo !== "projetos" || !IDs.test(projeto ?? "")) return null;
  const consulta = metodo === "GET" && acao === "fonte" && rota.length === 3;
  if (consulta) {
    const revisoes = busca.getAll("revision");
    if ([...busca.keys()].some((k) => k !== "revision") || revisoes.length > 1 ||
      (revisoes.length && !/^(0|[1-9][0-9]{0,12})$/.test(revisoes[0]))) return null;
  } else if (busca.size > 0) return null;
  const download = metodo === "GET" && acao === "runs" && IDs.test(run ?? "") &&
    arquivos === "arquivos" && ARQUIVOS.has(nome) && rota.length === 6;
  if (!consulta && !download && !(metodo === "GET" && rota.length === 2) &&
      !(metodo === "POST" && rota.length === 3 && ACOES.has(acao))) return null;
  return { caminho: "/v1/" + rota.join("/") + (busca.size ? "?" + busca.toString() : ""), arquivo: download ? nome : null };
}

async function lerComando(pedido: Request) {
  if (pedido.headers.get("content-type")?.split(";")[0].trim() !== "application/json") return null;
  const leitor = pedido.body?.getReader();
  if (!leitor) return null;
  const blocos: Uint8Array[] = [];
  let tamanho = 0;
  for (;;) {
    const { value, done } = await leitor.read();
    if (done) break;
    tamanho += value.byteLength;
    if (tamanho > 8192) {
      await leitor.cancel();
      return null;
    }
    blocos.push(value);
  }
  const texto = Buffer.concat(blocos).toString("utf8");
  try {
    const objeto = JSON.parse(texto);
    return objeto && typeof objeto === "object" && !Array.isArray(objeto) ? texto : null;
  } catch {
    return null;
  }
}

export async function encaminhar(pedido: Request, rota: string[], ambiente: Record<string, string | undefined>, enviar = fetch) {
  let host: URL;
  try {
    const autoridade = pedido.headers.get("host");
    if (!autoridade || /[/@?#\\]/.test(autoridade)) throw new Error();
    host = new URL(new URL(pedido.url).protocol + "//" + autoridade);
    if (!LOCAIS.has(host.hostname)) throw new Error();
  } catch {
    return erro("Abra o painel nesta máquina pelo endereço de loopback.", 403);
  }
  const origem = pedido.headers.get("origin");
  if ((origem && origem !== host.origin) || (!origem && pedido.method === "POST") ||
      pedido.headers.get("sec-fetch-site") === "cross-site") {
    return erro("A origem da solicitação não corresponde ao painel local.", 403);
  }
  const recurso = alvo(pedido.method, rota, new URL(pedido.url).searchParams);
  if (!recurso) return erro("Operação desconhecida.", 404);
  const token = ambiente.KORDA_OPERADOR_TOKEN?.trim();
  if (!token) return erro("Configure KORDA_OPERADOR_TOKEN no servidor local do painel.", 503);
  let base: URL;
  try {
    base = new URL(ambiente.KORDA_OPERADOR_URL || "http://127.0.0.1:8790");
    if (base.protocol !== "http:" || !LOCAIS.has(base.hostname) || base.username || base.password ||
      base.pathname !== "/" || base.search || base.hash) throw new Error();
  } catch {
    return erro("KORDA_OPERADOR_URL deve apontar para a raiz HTTP do serviço local.", 503);
  }
  const headers = new Headers({ Authorization: "Bearer " + token });
  let corpo: string | undefined;
  if (pedido.method === "POST") {
    corpo = (await lerComando(pedido)) ?? undefined;
    if (!corpo) return erro("O comando exige um objeto JSON de até 8 KiB.", 400);
    headers.set("Content-Type", "application/json");
  }
  try {
    const resposta = await enviar(new URL(recurso.caminho, base), {
      method: pedido.method, headers, body: corpo, cache: "no-store", redirect: "error",
      signal: AbortSignal.any([pedido.signal, AbortSignal.timeout(30000)]),
    });
    const saida = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    if (recurso.arquivo && resposta.ok) {
      saida.set("Content-Disposition", 'attachment; filename="' + recurso.arquivo + '"');
      saida.set("Content-Type", "application/octet-stream");
    } else {
      saida.set("Content-Type", "application/json");
    }
    return new Response(resposta.body, { status: resposta.status, headers: saida });
  } catch {
    return erro("Serviço local indisponível. Confira o endereço e se o operador está em execução.", 502);
  }
}
