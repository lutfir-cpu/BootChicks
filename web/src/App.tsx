import { useRef, useState } from "react";
import {
  AgentCard,
  BranchConnector,
  FinalArbitrationCard,
  Header,
  LaneConnector,
  MergeConnector,
  ScenarioInput,
} from "./components";
import { agents, initialScenario } from "./data";
import { mockNegotiationService } from "./mockService";
import type {
  AgentId,
  AgentResult,
  ArbitrationResult,
  Scenario,
  Status,
  Turn,
  WorkflowEvent,
} from "./types";

type AgentState = Record<Turn, Record<AgentId, AgentResult>>;

function initialAgents(): AgentState {
  const turn = (): Record<AgentId, AgentResult> => ({
    atc: { status: "waiting", logs: [] },
    pilot: { status: "waiting", logs: [] },
    ground: { status: "waiting", logs: [] },
  });
  return { 1: turn(), 2: turn() };
}

function initialArbitration(): ArbitrationResult {
  return {
    status: "waiting",
    logs: [],
    rankedPlans: [],
    safetyChecks: {},
    finalOutput: {},
  };
}

function applyEvent(
  event: WorkflowEvent,
  setAgents: React.Dispatch<React.SetStateAction<AgentState>>,
  setArbitration: React.Dispatch<React.SetStateAction<ArbitrationResult>>,
) {
  if (event.type === "agent-status" || event.type === "agent-log") {
    setAgents((previous) => {
      const current = previous[event.turn][event.agentId];
      const next =
        event.type === "agent-status"
          ? { ...current, status: event.status }
          : { ...current, logs: [...current.logs, event.log] };
      return {
        ...previous,
        [event.turn]: { ...previous[event.turn], [event.agentId]: next },
      };
    });
  } else if (event.type === "arbitration-status") {
    setArbitration((previous) => ({ ...previous, status: event.status }));
  } else if (event.type === "arbitration-log") {
    setArbitration((previous) => ({
      ...previous,
      logs: [...previous.logs, event.log],
    }));
  } else {
    setArbitration((previous) => ({ ...previous, ...event.result }));
  }
}

export default function App() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [agentResults, setAgentResults] = useState<AgentState>(initialAgents);
  const [arbitration, setArbitration] =
    useState<ArbitrationResult>(initialArbitration);
  const [status, setStatus] = useState<Status>("waiting");
  const traceRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function run() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setAgentResults(initialAgents());
    setArbitration(initialArbitration());
    setStatus("running");
    try {
      for await (const event of mockNegotiationService.run(
        scenario,
        controller.signal,
      )) {
        applyEvent(event, setAgentResults, setArbitration);
      }
      setStatus("complete");
    } catch (error) {
      if (controller.signal.aborted) return;
      const message =
        error instanceof Error
          ? error.message
          : "The replay failed. Please try again.";
      setStatus("error");
      setArbitration((previous) => ({
        ...previous,
        status: "error",
        error: message,
      }));
      setAgentResults((previous) => {
        const next = structuredClone(previous);
        for (const turn of [1, 2] as const)
          for (const agent of agents) {
            if (next[turn][agent.id].status === "running")
              next[turn][agent.id] = {
                ...next[turn][agent.id],
                status: "error",
                error: message,
              };
          }
        return next;
      });
    }
  }

  function showTrace() {
    traceRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    traceRef.current
      ?.querySelector<HTMLElement>(".logs")
      ?.focus({ preventScroll: true });
  }

  return (
    <div className="app-shell">
      <Header scenario={scenario} status={status} onTrace={showTrace} />
      <main className="workflow">
        <ScenarioInput
          scenario={scenario}
          onChange={setScenario}
          onRun={run}
          running={status === "running"}
        />
        <section aria-labelledby="turn-one-title">
          <h2 className="turn-title" id="turn-one-title">
            Turn 1 - Independent Constraint Identification
          </h2>
          <BranchConnector />
          <div className="agent-grid">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                turn={1}
                result={agentResults[1][agent.id]}
              />
            ))}
          </div>
        </section>
        <section aria-labelledby="turn-two-title">
          <h2 className="turn-title" id="turn-two-title">
            Turn 2 - Cross-Domain Plan Generation
          </h2>
          <LaneConnector />
          <div className="agent-grid">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                agent={agent}
                turn={2}
                result={agentResults[2][agent.id]}
              />
            ))}
          </div>
        </section>
        <section aria-labelledby="turn-three-title">
          <h2 className="turn-title" id="turn-three-title">
            Turn 3 - Final Arbitration and Convergence
          </h2>
          <MergeConnector />
          <FinalArbitrationCard result={arbitration} traceRef={traceRef} />
        </section>
      </main>
    </div>
  );
}
