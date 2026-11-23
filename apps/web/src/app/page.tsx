// Página provisória (passo 1 do plano): confere tema, fonte e tokens.
const swatches = [
  ["ink-900", "bg-ink-900"],
  ["ink-800", "bg-ink-800"],
  ["ink-500", "bg-ink-500"],
  ["ink-100", "bg-ink-100"],
  ["paper", "bg-paper border border-ink-100"],
  ["status-done", "bg-status-done"],
  ["status-waiting", "bg-status-waiting"],
  ["status-failed", "bg-status-failed"],
] as const;

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/korda-wordmark-black.svg" alt="Korda" className="h-8" />
      <h1 className="mt-10 text-3xl font-bold tracking-[-0.035em]">
        Tema carregado<span className="cursor-blink ml-2" aria-hidden />
      </h1>
      <p className="mt-2 text-ink-500">Inter 400 · 600 · 700, tokens do Korda Design System.</p>
      <ul className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {swatches.map(([name, cls]) => (
          <li key={name}>
            <div className={`h-14 rounded-[8px] ${cls}`} />
            <p className="mt-2 text-sm">{name}</p>
          </li>
        ))}
      </ul>
    </main>
  );
}
