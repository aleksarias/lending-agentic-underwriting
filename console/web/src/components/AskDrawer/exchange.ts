/**
 * The last question asked, and its answer, kept outside the drawer component.
 *
 * A question can take a minute and costs money. If the drawer is closed by accident (Escape, a click on the backdrop)
 * while the agent is working, the answer must not be lost, so the request's result is written here whether or not the
 * drawer is still mounted, and the drawer shows it when it is opened again. Memory only: a page reload clears it.
 */
import type { AskResponse } from "../../api/types";

export interface Exchange {
  /** the question that was sent */
  question: string;
  status: "idle" | "pending" | "done" | "error";
  data?: AskResponse;
  error?: unknown;
}

let exchange: Exchange = { question: "", status: "idle" };
let draft = "";
let current = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export const exchangeStore = {
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  getSnapshot: (): Exchange => exchange,
  /** Starts an exchange and returns its id; results of older exchanges are ignored. */
  begin(question: string): number {
    current += 1;
    exchange = { question, status: "pending" };
    emit();
    return current;
  },
  resolve(id: number, data: AskResponse) {
    if (id !== current) return;
    exchange = { question: exchange.question, status: "done", data };
    emit();
  },
  reject(id: number, error: unknown) {
    if (id !== current) return;
    exchange = { question: exchange.question, status: "error", error };
    emit();
  },
  clear() {
    current += 1;
    exchange = { question: "", status: "idle" };
    emit();
  },
};

export const getDraft = (): string => draft;
export const setDraft = (text: string): void => {
  draft = text;
};
