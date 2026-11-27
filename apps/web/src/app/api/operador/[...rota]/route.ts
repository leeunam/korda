import { encaminhar } from "@/lib/operador-proxy";

async function operador(pedido: Request, contexto: RouteContext<"/api/operador/[...rota]">) {
  const { rota } = await contexto.params;
  return encaminhar(pedido, rota, process.env);
}

export { operador as GET, operador as POST };
