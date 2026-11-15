import { describe, expect, it } from "vitest";

import type { DecisionTrace, TraceLedgerRow } from "../api/types";
import {
  VERDICT_ORDER,
  VERDICTS,
  attentionCount,
  fitnessSentence,
  httpUrl,
  ledgerFacts,
  prState,
  splitTasks,
  verdictMeta,
} from "./traceability";

const row = (over: Partial<TraceLedgerRow> = {}): TraceLedgerRow => ({
  adr_id: 1,
  number: 1,
  title: "Tokenize in the vault",
  status: "accepted",
  verdict: "honored",
  reason: "",
  tasks: 0,
  implementing: 0,
  done: 0,
  prs: 0,
  merged: 0,
  fitness: 0,
  violated: 0,
  reviews_checked: 0,
  open_drift: 0,
  ...over,
});

describe("traceability", () => {
  it("labels every verdict, worst first", () => {
    expect(VERDICT_ORDER).toHaveLength(Object.keys(VERDICTS).length);
    expect(VERDICT_ORDER[0]).toBe("violated");
    expect(verdictMeta("honored").label).toBe("Honored");
    expect(verdictMeta("something_new").label).toBe("something new");
  });

  it("counts the decisions that need a person", () => {
    const rows = [row({ verdict: "violated" }), row({ verdict: "at_risk" }), row()];
    expect(attentionCount(rows)).toBe(2);
  });

  it("states the ledger counts, leaving out zeros", () => {
    expect(ledgerFacts(row())).toEqual([]);
    expect(
      ledgerFacts(row({ tasks: 3, done: 2, prs: 2, merged: 1, fitness: 2, violated: 1 })),
    ).toEqual(["2/3 tasks done", "1/2 PRs merged", "1/2 rules broken"]);
    expect(ledgerFacts(row({ fitness: 1, reviews_checked: 1, open_drift: 2 }))).toEqual([
      "1 fitness rule, none broken",
      "1 review checked it",
      "2 open drift",
    ]);
  });

  it("splits implementing work from governed work", () => {
    const trace = {
      tasks: [
        { task_id: 1, key: "PAY-1", name: "a", status: null, done: false, implements: true, governed: true },
        { task_id: 2, key: null, name: "b", status: null, done: true, implements: false, governed: true },
      ],
    } as DecisionTrace;
    const { implementing, governed } = splitTasks(trace);
    expect(implementing.map((t) => t.task_id)).toEqual([1]);
    expect(governed.map((t) => t.task_id)).toEqual([2]);
  });

  it("links only plain http(s) URLs", () => {
    expect(httpUrl("https://github.com/acme/pay/pull/7")).toBe("https://github.com/acme/pay/pull/7");
    expect(httpUrl("javascript:alert(1)")).toBeNull();
    expect(httpUrl("not a url")).toBeNull();
    expect(httpUrl(null)).toBeNull();
  });

  it("phrases PR states and fitness rules", () => {
    expect(prState({ state: "closed", merged: true })).toBe("merged");
    expect(prState({ state: "open", merged: false })).toBe("open");
    expect(prState({ state: "closed", merged: false })).toBe("closed");
    expect(fitnessSentence({ kind: "forbid", source: "web", target: "db" })).toBe(
      "web must not depend on db",
    );
    expect(fitnessSentence({ kind: "require", source: "pay", target: "vault" })).toBe(
      "pay must depend on vault",
    );
  });
});
