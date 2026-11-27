import Link from "next/link";
import { RunApp } from "@/components/RunApp";

export default function Home() {
  // Abaixo do breakpoint `md` (768px) a interface não é suportada: mostramos só um aviso.
  // Feito em CSS para não depender de JS nem causar diferença de hidratação.
  return (
    <>
      <div className="hidden md:contents">
        <RunApp />
        <Link href="/operador" lang="pt-BR" className="fixed top-7 left-36 z-10 rounded-lg border border-rule bg-canvas px-3 py-1.5 text-sm font-semibold text-ink hover:bg-hover">Painel do operador</Link>
      </div>
      <div className="flex h-dvh flex-col items-center justify-center gap-6 bg-page px-6 text-center md:hidden">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/korda-wordmark-white.svg" alt="Korda" className="h-5 w-auto select-none" />
        <div className="flex max-w-xs flex-col gap-2">
          <h1 className="text-base font-semibold text-ink">Open Korda on a laptop</h1>
          <p className="text-sm text-muted">
            This graph needs a wider window.
          </p>
        </div>
        <Link href="/operador" lang="pt-BR" className="rounded-lg bg-canvas px-4 py-2 text-sm font-semibold text-ink shadow-card">Painel do operador</Link>
      </div>
    </>
  );
}
