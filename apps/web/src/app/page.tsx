import { Suspense } from "react";
import { GraphPreview } from "@/components/GraphPreview";

export default function Home() {
  return (
    <Suspense fallback={<p className="p-4 text-ink-500">Carregando…</p>}>
      <GraphPreview />
    </Suspense>
  );
}
