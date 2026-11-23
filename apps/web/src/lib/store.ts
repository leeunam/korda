import { useSyncExternalStore } from "react";
import type { RunEvent } from "./events";

/**
 * Onde os eventos vivem. Hoje: memória do navegador.
 * Um backend real (Convex, Supabase, ...) implementa esta mesma interface depois.
 */
export interface EventStore {
  list(): RunEvent[];
  append(event: RunEvent): void;
  subscribe(listener: (events: RunEvent[]) => void): () => void;
  reset(): void;
}

const EMPTY: RunEvent[] = [];

export function createMemoryStore(): EventStore {
  let events: RunEvent[] = EMPTY;
  const listeners = new Set<(events: RunEvent[]) => void>();
  const emit = () => listeners.forEach((l) => l(events));

  return {
    list: () => events,
    append(event) {
      events = [...events, event];
      emit();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    reset() {
      if (events === EMPTY) return;
      events = EMPTY;
      emit();
    },
  };
}

export function useRunEvents(store: EventStore): RunEvent[] {
  return useSyncExternalStore(store.subscribe, store.list, () => EMPTY);
}
