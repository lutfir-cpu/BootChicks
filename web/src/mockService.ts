import { completedArbitration } from "./data";
import type {
  AgentId,
  LogEntry,
  NegotiationService,
  Scenario,
  Turn,
  WorkflowEvent,
} from "./types";

const roles: AgentId[] = ["atc", "pilot", "ground"];
const messages: Record<Turn, Record<AgentId, string[]>> = {
  1: {
    atc: [
      "Receiving arrival scenario and runway state",
      "Checking wake separation and available approach slots",
      "Runway constraint summary complete",
    ],
    pilot: [
      "Reading fuel and crew limits",
      "Estimating approach and taxi fuel margin",
      "Flight deck constraints recorded",
    ],
    ground: [
      "Checking gate reserve and turnaround crews",
      "Reviewing baggage and taxiway flow",
      "Ground capacity constraints recorded",
    ],
  },
  2: {
    atc: [
      "Comparing constraints from all three domains",
      "Generating arrival sequence options A, B and C",
      "Three ATC plans ready",
    ],
    pilot: [
      "Evaluating cross-domain timing proposals",
      "Generating fuel-aware options A, B and C",
      "Three pilot plans ready",
    ],
    ground: [
      "Matching gates and crews to arrival windows",
      "Generating turnaround options A, B and C",
      "Three ground plans ready",
    ],
  },
};

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(signal.reason);
    const timeout = window.setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    const abort = () => {
      window.clearTimeout(timeout);
      reject(signal?.reason);
    };
    signal?.addEventListener("abort", abort, { once: true });
  });
}

function log(message: string): LogEntry {
  return {
    time: new Date().toLocaleTimeString("en-GB", { hour12: false }),
    message,
  };
}

export const mockNegotiationService: NegotiationService = {
  async *run(
    scenario: Scenario,
    signal?: AbortSignal,
  ): AsyncIterable<WorkflowEvent> {
    for (const turn of [1, 2] as const) {
      for (const agentId of roles)
        yield { type: "agent-status", turn, agentId, status: "running" };
      for (let step = 0; step < 3; step++) {
        await wait(320, signal);
        for (const agentId of roles) {
          yield {
            type: "agent-log",
            turn,
            agentId,
            log: log(messages[turn][agentId][step]),
          };
        }
      }
      for (const agentId of roles)
        yield { type: "agent-status", turn, agentId, status: "complete" };
    }
    yield { type: "arbitration-status", status: "running" };
    for (const message of [
      `Nine candidate plans received for ${scenario.flight}`,
      "Ranking delay, fuel, connections and ground impact",
      "Checking wake, runway, taxiway, gate, crew and fuel constraints",
      "Plan A selected; final recommendation ready",
    ]) {
      await wait(380, signal);
      yield { type: "arbitration-log", log: log(message) };
    }
    yield { type: "complete", result: completedArbitration };
    yield { type: "arbitration-status", status: "complete" };
  },
};
