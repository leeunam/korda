import { describe, expect, it, vi } from "vitest";
import { encaminhar } from "./operador-proxy";

const env = { KORDA_OPERADOR_TOKEN: "credencial-ficticia" };
const prefixo = ["projetos", "demo-01"];
function pedido(caminho: string, metodo = "GET", cabecalhos: Record<string, string> = {}, corpo?: string) {
  return new Request("http://127.0.0.1:3000/api/operador/projetos/demo-01" + caminho, {
    method: metodo, headers: { Host: "127.0.0.1:3000", ...cabecalhos }, body: corpo,
  });
}
const jsonLocal = { Origin: "http://127.0.0.1:3000", "Content-Type": "application/json" };

describe("ponte privada do painel", () => {
  it("só autentica no servidor a consulta à revisão congelada", async () => {
    const enviar = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ revision: 2, sha256: "abc" }));
    const res = await encaminhar(pedido("/fonte?revision=2"), [...prefixo, "fonte"], env, enviar);
    const [url, req] = enviar.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8790/v1/projetos/demo-01/fonte?revision=2");
    expect(new Headers(req?.headers).get("Authorization")).toBe("Bearer credencial-ficticia");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(res.headers.has("Authorization")).toBe(false);
    expect(await res.json()).toEqual({ revision: 2, sha256: "abc" });
  });
  it("encaminha a decisão explícita com a versão, preserva recusas e filtra cabeçalhos", async () => {
    const corpo = JSON.stringify({ plan_version: "abc", aprovar: false, pessoa: "Pessoa fictícia" });
    const enviar = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: "versão substituída" }, {
      status: 409, headers: { "Set-Cookie": "nao-repassar", Authorization: "nao-repassar" },
    }));
    const res = await encaminhar(pedido("/decidir-plano", "POST", jsonLocal, corpo), [...prefixo, "decidir-plano"], env, enviar);
    expect(enviar.mock.calls[0][1]?.body).toBe(corpo);
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "versão substituída" });
    expect(res.headers.has("Set-Cookie")).toBe(false);
    expect(res.headers.has("Authorization")).toBe(false);
  });
  it("recusa origem, host, destino e arquivos fora do escopo sem consultar o serviço", async () => {
    const enviar = vi.fn<typeof fetch>();
    const chamadas: Array<[Request,string[],Record<string, string | undefined>,number]> = [
      [pedido("", "GET", { Host: "painel.exemplo" }), prefixo, env, 403],
      [pedido("", "GET", { "Sec-Fetch-Site": "cross-site" }), prefixo, env, 403],
      [pedido("/executar", "POST", { ...jsonLocal, Origin: "https://outro.test" }, "{}"), [...prefixo,"executar"], env, 403],
      [pedido("/executar", "POST", {}, "{}"), [...prefixo,"executar"], env, 403],
      [pedido(""), ["projetos", ".."], env, 404],
      [pedido("/fonte?revision=1&revision=2"), [...prefixo,"fonte"], env, 404],
      [pedido(""), [...prefixo,"runs","run-1","arquivos","controle.sqlite"], env, 404],
      [pedido(""), prefixo, {}, 503],
      [pedido(""), prefixo, { ...env, KORDA_OPERADOR_URL: "https://servico.exemplo" }, 503],
      [pedido("/executar", "POST", jsonLocal, JSON.stringify({ texto: "a".repeat(8193) })), [...prefixo,"executar"], env, 400],
    ];
    for (const [r, rota, ambiente, status] of chamadas) {
      expect((await encaminhar(r, rota, ambiente, enviar)).status).toBe(status);
    }
    expect(enviar).not.toHaveBeenCalled();
  });
  it("só envia cabeçalho de download quando o serviço autoriza o arquivo", async () => {
    const rota = [...prefixo, "runs", "r1", "arquivos", "pacote.zip"];
    const enviar = vi.fn<typeof fetch>().mockResolvedValueOnce(Response.json({ error: "Aguardando promoção" }, { status: 409 }))
      .mockResolvedValueOnce(new Response(new Uint8Array([80,75])));
    const bloqueado = await encaminhar(pedido("/runs/r1/arquivos/pacote.zip"), rota, env, enviar);
    expect(bloqueado.headers.has("Content-Disposition")).toBe(false);
    const liberado = await encaminhar(pedido("/runs/r1/arquivos/pacote.zip"), rota, env, enviar);
    expect(liberado.headers.get("Content-Disposition")).toContain('filename="pacote.zip"');
    expect(new Uint8Array(await liberado.arrayBuffer())).toEqual(new Uint8Array([80,75]));
  });
});
