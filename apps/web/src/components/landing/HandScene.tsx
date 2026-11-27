"use client";

import { useEffect, useRef } from "react";

/*
 * Ilustração do hero: um bando de cursores de mão (os agentes) flui da esquerda e se
 * reúne diante do dedo indicador de uma mão humana. Tudo num único SVG, em coordenadas
 * fixas (cena de VIEW_W de largura; recorte visível em VIEW), com `slice` para caber em qualquer largura.
 */

const VIEW_W = 1440;
// Ponto de encontro: centro da viewBox, que o `xMidYMid slice` mantém no centro da tela.
const TIP = { x: VIEW_W / 2, y: 318 };
// Recorte visível: só a faixa com conteúdo (cursores e braço), ~3,6:1, centrado em TIP.x.
// Mais largo que a cena para o conjunto ficar menor na tela; o contêiner usa a mesma proporção.
const VIEW = { x: TIP.x - 816, y: 95, w: 1632, h: 455 };
const GAP = 22; // meia distância entre o dedo humano e o dedo dos cursores, simétrica em torno de TIP

// Cursor de mão em pixel art, apontando para a direita. k = contorno, w = preenchimento.
const CURSOR = [
  "....kkkkkkkkkkk.",
  "...kwwwwwwwwwwwk",
  "...kwwwwwwwwwwwk",
  "kkkwwwwwkkkkkkk.",
  "kwwwwwwwwwwk....",
  "kwwwwwwwkkkk....",
  "kwwwwwwwwwwk....",
  "kwwwwwwwkkk.....",
  "kwwwwwwwwwk.....",
  ".kwwwwwwwk......",
  "..kkkkkkk.......",
];
const CURSOR_SCALE = 1.35;

// Braço pintado (Higgsfield, GPT Image 2.6; repintura em grisalha, estilo afresco, inspirada em
// "A Criação de Adão"): 1064×576, fundo preto puro, ponta do indicador em (67, 270) na imagem.
const ARM = { src: "/landing-arm.webp", w: 1064, h: 576, tipX: 67, tipY: 270 };
const ARM_WIDTH = 780; // largura na viewBox
const ARM_SCALE = ARM_WIDTH / ARM.w;
const ARM_X = TIP.x + GAP - ARM.tipX * ARM_SCALE; // ponta do dedo a GAP à direita de TIP
// O fim da foto fica dentro do recorte: a máscara zera a opacidade até lá, sem borda visível.

// PRNG com semente: as mesmas posições no servidor e no cliente (sem erro de hidratação).
function mulberry32(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Um agente: posição final na formação e como ele entra em cena. */
type Agent = {
  x: number;
  y: number;
  angle: number;
  scale: number;
  fromX: number;
  fromY: number;
  delay: number;
  duration: number;
  driftPhase: number; // movimento ocioso depois de pousar: fase e ritmo próprios de cada cursor
  driftSpeed: number;
};

const DRIFT_X = 1.6; // amplitude do balanço ocioso, em unidades da cena (quase imperceptível)
const DRIFT_Y = 2.4;

const START_X = 60; // cursor mais à esquerda da formação
const END_X = TIP.x - GAP; // ponta do dedo do cursor líder
const FLOCK_SIZE = 42;
// Distância mínima entre cursores (nenhum se sobrepõe): apertada na cunha, folgada à esquerda.
const minDist = (u: number) => 27 + 34 * u;
const FIRST_ARRIVAL = 0.9; // s: o líder, mais perto do dedo, chega primeiro
const ARRIVAL_SPREAD = 1.0; // s: o mais distante do dedo chega este tempo depois

/**
 * Formação parada em ponta de flecha: uma cunha densa que afina até o dedo e, à esquerda,
 * cursores esparsos num leque mais aberto (altura ≈ metade do comprimento). Semente fixa.
 */
function buildFlock(): Agent[] {
  const rand = mulberry32(11);
  const length = END_X - START_X;
  // Meia-altura do envelope em função de u (0 na ponta, 1 na extremidade esquerda).
  const halfHeight = (u: number) => 12 + 0.3 * length * Math.pow(u, 0.7);
  const spots = [{ x: END_X, y: TIP.y }]; // o líder, exatamente no ponto de encontro
  for (let tries = 0; spots.length < FLOCK_SIZE && tries < 8000; tries++) {
    const u = 0.04 + 0.96 * Math.pow(rand(), 2.2); // a maioria na cunha, perto da ponta
    const x = END_X - u * length;
    const y = TIP.y + (rand() * 2 - 1) * halfHeight(u);
    if (spots.every((p) => Math.hypot(p.x - x, p.y - y) >= minDist(u))) spots.push({ x, y });
  }
  const fromTip = spots.map((p) => Math.hypot(TIP.x - p.x, TIP.y - p.y));
  const maxFromTip = Math.max(...fromTip);
  return spots.map(({ x, y }, i) => {
    const scale = 0.85 + rand() * 0.3;
    // Percurso curto: a maioria já começa na tela, só um pouco à esquerda do lugar final.
    const fromX = x - (70 + rand() * 150);
    const fromY = y + (rand() * 2 - 1) * 18;
    // Mais longe e maior = mais lento: a duração cresce com a distância percorrida e com o tamanho.
    const duration = (0.45 + Math.hypot(x - fromX, y - fromY) / 500) * scale;
    // Ordem de chegada pela distância ao dedo humano; o atraso é calculado a partir dela.
    const arrival = FIRST_ARRIVAL + ARRIVAL_SPREAD * (fromTip[i] / maxFromTip);
    return {
      x,
      y,
      angle: ((Math.atan2(TIP.y - y, TIP.x - x) * 180) / Math.PI) * 0.6,
      scale,
      fromX,
      fromY,
      delay: Math.max(0, arrival - duration),
      duration,
      driftPhase: rand() * Math.PI * 2,
      driftSpeed: 0.35 + rand() * 0.3,
    };
  });
}

const AGENTS = buildFlock();

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

/** Quadro de um agente `time` segundos após o início da entrada; `idle` liga o balanço contínuo. */
function frameFor(agent: Agent, time: number, idle: boolean) {
  const p = Math.min(1, Math.max(0, (time - agent.delay) / agent.duration));
  const k = easeOutCubic(p);
  // O balanço cresce junto com a chegada (× k), então não há salto quando o cursor pousa.
  const w = time * agent.driftSpeed + agent.driftPhase;
  const dx = idle ? Math.sin(w) * DRIFT_X * k : 0;
  const dy = idle ? Math.sin(w * 0.8 + agent.driftPhase * 1.7) * DRIFT_Y * k : 0;
  const x = agent.fromX + (agent.x - agent.fromX) * k + dx;
  const y = agent.fromY + (agent.y - agent.fromY) * k + dy;
  const s = CURSOR_SCALE * agent.scale;
  // Âncora na ponta do dedo do cursor (16, 1.5), para que o líder toque o ponto de encontro.
  const transform = `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${agent.angle.toFixed(1)}) scale(${s.toFixed(3)}) translate(-16 -1.5)`;
  return { transform, opacity: Math.min(1, p * 4).toFixed(3) };
}

export function HandScene({ className }: { className?: string }) {
  const refs = useRef<(SVGUseElement | null)[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);

  // Entrada única: os cursores voam até a formação e param. Com movimento reduzido, já aparecem no lugar.
  // Entrada (os cursores voam até a formação) e depois um balanço leve e contínuo.
  // O loop só roda com a cena visível. Com movimento reduzido, tudo aparece parado no lugar.
  useEffect(() => {
    const apply = (time: number, idle: boolean) => {
      AGENTS.forEach((agent, i) => {
        const el = refs.current[i];
        if (!el) return;
        const f = frameFor(agent, time, idle);
        el.setAttribute("transform", f.transform);
        el.setAttribute("opacity", f.opacity);
      });
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      apply(Infinity, false);
      return;
    }
    const svg = svgRef.current;
    if (!svg) return;
    // Começa já (a entrada não depende do observer); o observer só pausa o loop fora da tela.
    const start = performance.now();
    const tick = (now: number) => {
      apply((now - start) / 1000, true);
      frame = requestAnimationFrame(tick);
    };
    let running = true;
    let frame = requestAnimationFrame(tick);
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !running) {
        running = true;
        frame = requestAnimationFrame(tick);
      } else if (!entry.isIntersecting && running) {
        running = false;
        cancelAnimationFrame(frame);
      }
    });
    io.observe(svg);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <svg
      ref={svgRef}
      viewBox={`${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`}
      preserveAspectRatio="xMidYMid slice"
      className={className}
      role="img"
      aria-label="A flock of cursor hands gathering at the fingertip of a human hand"
    >
      <defs>
        <g id="agent-cursor" shapeRendering="crispEdges">
          {CURSOR.flatMap((row, y) =>
            [...row].map((c, x) =>
              c === "." ? null : (
                <rect key={`${x}-${y}`} x={x} y={y} width={1.04} height={1.04} fill={c === "k" ? "#050506" : "#fff"} />
              ),
            ),
          )}
        </g>

        {/* O braço se dissolve no escuro: mão inteira visível, antebraço escurece rumo à borda. */}
        <linearGradient
          id="arm-fade-gradient"
          gradientUnits="userSpaceOnUse"
          x1={TIP.x + 250}
          y1={0}
          x2={ARM_X + ARM_WIDTH}
          y2={0}
        >
          <stop offset="0" stopColor="#fff" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0.42" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <mask id="arm-fade" maskUnits="userSpaceOnUse" x={VIEW.x} y={VIEW.y} width={VIEW.w} height={VIEW.h}>
          <rect x={VIEW.x} y={VIEW.y} width={VIEW.w} height={VIEW.h} fill="url(#arm-fade-gradient)" />
        </mask>
      </defs>

      {/* `lighten`: o preto da foto some no fundo da página, sem retângulo visível.
          O braço é o elemento maior e mais pesado: entra junto, mas devagar, e é o último a parar (globals.css). */}
      <g className="arm-enter" style={{ mixBlendMode: "lighten" }}>
        <g className="arm-float">
          <image
            mask="url(#arm-fade)"
            href={ARM.src}
            x={ARM_X}
            y={TIP.y - ARM.tipY * ARM_SCALE}
            width={ARM_WIDTH}
            height={ARM.h * ARM_SCALE}
          />
        </g>
      </g>

      {AGENTS.map((agent, i) => {
        const { transform, opacity } = frameFor(agent, 0, false);
        return (
          <use
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            href="#agent-cursor"
            transform={transform}
            opacity={opacity}
          />
        );
      })}
    </svg>
  );
}
