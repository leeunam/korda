import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Silkscreen, Source_Serif_4 } from "next/font/google";
import { HandScene } from "@/components/landing/HandScene";
import { HEADER_GLASS } from "@/components/landing/glass";
import { MobileMenu } from "@/components/landing/MobileMenu";
import { PixelText } from "@/components/landing/PixelText";
import { Reveal } from "@/components/landing/Reveal";

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-serif",
});

// Fonte pixel do cabeçalho (desenhada numa grade de 8 px: nítida em múltiplos de 4 px).
const pixel = Silkscreen({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-pixel",
});

// Safari usa a theme-color para colorir a barra e a área de overscroll.
export const viewport: Viewport = { themeColor: "#000" };

export const metadata: Metadata = {
  title: "Korda · Human judgment, agent hands",
  description: "Korda turns client conversations into approved plans and tested data deliveries.",
};

const REPO = "https://github.com/leeunam/korda";

// Só links que levam a algum lugar: as seções abaixo do hero, o repositório e a documentação. A demo é linkada em "How it works".
const NAV = [
  { label: "Product", href: "#about" },
  { label: "How it works", href: "#how" },
  { label: "Team", href: "#team" },
  { label: "GitHub", href: REPO },
  { label: "Docs", href: `${REPO}/tree/main/docs` },
];

// Coluna de texto das seções abaixo do hero (mesma tipografia em todas).
const SECTION = "mx-auto max-w-[35rem] scroll-mt-24 px-4 pb-32 font-mono text-[15px] leading-[1.8] text-[#c6c6ca]";
const LABEL = "mb-6 tracking-[0.04em] text-white uppercase";
const PIXEL = "font-(family-name:--font-pixel) text-[12px] uppercase";

// Etapas do fluxo (README → "O que vamos construir"). `gate` marca a aprovação humana ao fim da etapa.
const STEPS = [
  {
    title: "Understand",
    body: "Our agents interview your team, inspect the sources and write down what is still unclear. A gap stays a gap until someone answers it: nothing is assumed.",
  },
  {
    title: "Plan",
    body: "Indicators, business rules and acceptance tests go into one versioned plan, with the evidence behind each rule.",
    gate: "Approval 1 · you sign off this version of the plan",
  },
  {
    title: "Build & test",
    body: "Agents write the models and run the tests in an isolated environment. They get at most three fixes per step, then stop and ask a person.",
  },
  {
    title: "Deliver",
    body: "You see the results next to the tests they passed. Nothing is promoted until you say so.",
    gate: "Approval 2 · you authorize the delivery to its destination",
  },
];

// Equipe (README → "Equipe"). Sem cargos: o README não define papéis.
const TEAM = [
  { name: "Leunam Sousa", github: "leeunam" },
  { name: "José Lima", github: "jlimaz" },
  { name: "Marcus Felipe", github: "m4rcusml" },
  { name: "Gabriel Marques", github: "Gabriel-smm" },
];

function Header() {
  const link = "transition-colors hover:text-white";
  return (
    // Cabeçalho flutuante: barra arredondada, presa ao topo ao rolar, com fundo translúcido e desfoque.
    <header className="sticky top-3 z-50 px-3 pt-3 sm:px-4">
      <div className="relative isolate mx-auto flex h-14 max-w-270 items-center justify-between gap-6 px-5 sm:px-8">
        {/* O vidro fica numa camada à parte: um backdrop-filter no próprio div impediria o painel do menu
            (descendente dele) de desfocar a página por trás. */}
        <span aria-hidden className={`absolute inset-0 -z-10 ${HEADER_GLASS}`} />
        <Link href="/" aria-label="Korda home" className="shrink-0">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/korda-wordmark-white.svg" alt="Korda" className="h-4.5 w-auto select-none" />
        </Link>

        {/* Tudo à direita; em telas pequenas, os links vão para o menu hambúrguer. */}
        <nav
          aria-label="Main"
          className="hidden items-center gap-8 font-(family-name:--font-pixel) text-[12px] text-white/60 uppercase md:flex"
        >
          {NAV.map((item) => (
            <a key={item.label} href={item.href} className={link}>
              {item.label}
            </a>
          ))}
        </nav>
        <MobileMenu items={NAV} />
      </div>
    </header>
  );
}

export default function Landing() {
  return (
    <main className={`${serif.variable} ${pixel.variable} min-h-dvh bg-black text-white`}>
      {/* <html>/<body> pretos só nesta página: o overscroll mostra o fundo da raiz. Sai junto com a página. */}
      <style>{"html,body{background:#000}"}</style>
      <Header />

      {/* A partir de md o hero ocupa a tela inteira (menos o cabeçalho); no celular o texto vem logo abaixo. */}
      <section className="relative flex flex-col justify-center overflow-hidden pb-4 md:min-h-[calc(100dvh-4.25rem)] md:pb-12">
        <h1
          className="relative z-10 mx-auto max-w-5xl px-4 pt-16 text-center text-[clamp(2rem,3.6vw,3.5rem)] leading-[1.06] tracking-[-0.02em] sm:pt-20"
          style={{ fontFamily: "var(--font-serif)" }}
        >
          <span className="sr-only">Human judgment, agent hands.</span>
          <span aria-hidden className="rise-in block" style={{ animationDelay: "0ms" }}>
            Human judgment,
          </span>
          <span aria-hidden className="rise-in block" style={{ animationDelay: "140ms" }}>
            <PixelText text="agent hands." fontFamily={serif.style.fontFamily} />
          </span>
        </h1>

        {/* Altura na proporção do recorte da cena (1632 × 455 ≈ 27,88vw). */}
        <HandScene className="mt-2 block h-[clamp(220px,27.88vw,520px)] w-full" />

        {/* Indicador de rolagem (só a partir de md; no celular a seção seguinte já aparece): leva à seção seguinte. */}
        <a
          href="#about"
          aria-label="Scroll to learn more"
          className="rise-in absolute inset-x-0 bottom-4 z-10 mx-auto hidden w-fit md:block p-2 text-white/45 transition-colors hover:text-white"
          style={{ animationDelay: "1200ms" }}
        >
          {/* Seta em pixel art: só a ponta (grade 5 × 3, 3 px por célula). */}
          <svg
            aria-hidden
            viewBox="0 0 5 3"
            width="15"
            height="9"
            shapeRendering="crispEdges"
            className="scroll-cue block fill-current"
          >
            <path d="M0 0h1v1H0zM4 0h1v1H4zM1 1h1v1H1zM3 1h1v1H3zM2 2h1v1H2z" />
          </svg>
        </a>
      </section>

      <Reveal id="about" className={`${SECTION} pt-10 md:pt-24`}>
        <h2 className={LABEL}>A data consultancy powered by AI</h2>
        <p className="mb-6">
          Korda is a data consultancy run by AI agents. It starts from a simple idea: the people who understand the
          business should decide what gets built, and agents should do the building.
        </p>
        <p>
          Our agents talk to your team, inspect your sources, write the models and run the tests. You stay in charge:
          you approve the plan before anything runs, and you approve the delivery before it ships. Everything in between
          is evidence you can check.
        </p>
      </Reveal>

      <Reveal id="how" className={SECTION}>
        <h2 className={LABEL}>How it works</h2>
        <p className="mb-10">
          Four steps, two signatures. Agents do the work in between; a person decides at each gate.
        </p>
        {/* Linha do tempo: cada etapa é um ponto na borda; as aprovações são marcos brancos que cruzam a linha. */}
        <ol className="border-l border-white/12">
          {STEPS.map((step, i) => (
            <li key={step.title} className="relative pb-10 pl-7 last:pb-0">
              <span aria-hidden className="absolute top-[0.7em] -left-[4px] size-[7px] bg-[#595959]" />
              <h3 className="flex items-baseline gap-3 text-white uppercase">
                <span className={`${PIXEL} text-white/40`}>{String(i + 1).padStart(2, "0")}</span>
                <span className="tracking-[0.04em]">{step.title}</span>
              </h3>
              <p className="mt-2">{step.body}</p>
              {step.gate && (
                <p
                  className={`${PIXEL} relative mt-6 -ml-7 border-y border-dashed border-white/20 py-3 pl-7 leading-normal text-white`}
                >
                  <span
                    aria-hidden
                    className="absolute top-1/2 -left-[6px] size-[11px] -translate-y-1/2 rotate-45 bg-white"
                  />
                  {step.gate}
                </p>
              )}
            </li>
          ))}
        </ol>
        <p className="mt-10 text-[13px] text-white/45">
          The{" "}
          <Link
            href="/run"
            className="text-white underline decoration-white/30 underline-offset-4 transition-colors hover:decoration-white"
          >
            demo
          </Link>{" "}
          walks a fictional carrier through this flow, on synthetic ERP, TMS and CT-e data.
        </p>
      </Reveal>

      <Reveal id="team" className={SECTION}>
        <h2 className={LABEL}>Team Undefined</h2>
        <p className="mb-10">Korda is built by four people for Hack Brasil 2026.</p>
        <ul className="border-t border-white/12">
          {TEAM.map((person) => (
            <li key={person.name} className="flex items-baseline justify-between gap-4 border-b border-white/12 py-3">
              <span className="text-white">{person.name}</span>
              {person.github ? (
                <a
                  href={`https://github.com/${person.github}`}
                  className={`${PIXEL} text-white/45 transition-colors hover:text-white`}
                >
                  @{person.github}
                </a>
              ) : (
                <span aria-hidden className={`${PIXEL} text-white/25`}>
                  —
                </span>
              )}
            </li>
          ))}
        </ul>
        {/* Piada com o nome da equipe, em forma de comentário de código. */}
        <p aria-hidden className="mt-6 text-[13px] text-white/30">
          const team = undefined; <span className="text-white/20">{"// it's four people, actually"}</span>
        </p>
      </Reveal>
    </main>
  );
}
