"use client";

import { useEffect, useRef, type ComponentProps } from "react";

/**
 * Seção cujos filhos sobem e saem do desfoque, em sequência, quando ela entra na tela.
 *
 * O HTML do servidor chega visível: o conteúdo só é escondido depois que o JS monta (`data-reveal="armed"`),
 * e só se o usuário aceitar movimento. Sem JS ou com movimento reduzido, nada fica oculto.
 * O atributo é escrito direto no DOM (o React não o renderiza), para não re-renderizar a seção.
 */
export function Reveal({ children, ...props }: ComponentProps<"section">) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (typeof IntersectionObserver === "undefined") return;

    el.dataset.reveal = "armed";
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          el.dataset.reveal = "shown";
          observer.disconnect();
        }
      },
      // Dispara quando o topo da seção já passou um pouco da borda inferior da tela.
      { rootMargin: "0px 0px -15% 0px" },
    );
    observer.observe(el);
    return () => {
      observer.disconnect();
      delete el.dataset.reveal;
    };
  }, []);

  return (
    <section ref={ref} {...props}>
      {children}
    </section>
  );
}
