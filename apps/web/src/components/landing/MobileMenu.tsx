"use client";

import { useEffect, useId, useRef, useState } from "react";

import { HEADER_GLASS } from "./glass";

type Item = { label: string; href: string };

/**
 * Menu do cabeçalho abaixo de `md`: um botão hambúrguer que abre os links num painel sob a barra.
 *
 * Fecha ao escolher um link, com Esc, ao clicar fora ou ao alargar a tela até `md` (onde a nav inline volta).
 * O painel é posicionado em relação à barra (`relative`), com o mesmo vidro dela.
 */
export function MobileMenu({ items }: { items: Item[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      buttonRef.current?.focus();
    };
    const onPointer = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const wide = window.matchMedia("(min-width: 48rem)");
    const onWide = () => wide.matches && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    wide.addEventListener("change", onWide);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="md:hidden">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? "Close menu" : "Open menu"}
        onClick={() => setOpen((v) => !v)}
        className="-mr-2 grid size-10 place-items-center text-white/60 transition-colors hover:text-white"
      >
        {/* Ícones em pixel art (grade 7 × 5 / 5 × 5, 2–3 px por célula), como a seta do hero. */}
        {open ? (
          <svg aria-hidden viewBox="0 0 5 5" width="15" height="15" shapeRendering="crispEdges" className="fill-current">
            <path d="M0 0h1v1H0zM4 0h1v1H4zM1 1h1v1H1zM3 1h1v1H3zM2 2h1v1H2zM1 3h1v1H1zM3 3h1v1H3zM0 4h1v1H0zM4 4h1v1H4z" />
          </svg>
        ) : (
          <svg aria-hidden viewBox="0 0 7 5" width="21" height="15" shapeRendering="crispEdges" className="fill-current">
            <path d="M0 0h7v1H0zM0 2h7v1H0zM0 4h7v1H0z" />
          </svg>
        )}
      </button>

      <nav
        id={panelId}
        aria-label="Main"
        hidden={!open}
        className={`absolute inset-x-0 top-full mt-2 p-2 ${HEADER_GLASS}`}
      >
        <ul className="font-(family-name:--font-pixel) text-[12px] text-white/60 uppercase">
          {items.map((item) => (
            <li key={item.label}>
              <a
                href={item.href}
                onClick={() => setOpen(false)}
                className="block rounded-xl px-4 py-3 transition-colors hover:bg-white/6 hover:text-white"
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
