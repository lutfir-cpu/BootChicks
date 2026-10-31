export type Status = "waiting" | "running" | "complete" | "error";
export type AgentId = "atc" | "pilot" | "ground";
export type Turn = 1 | 2;

export interface Scenario {
  airline: string;
  origin: string;
  destination: string;
  disruption: string;
  flight: string;
}

export interface LogEntry {
  time: string;
  message: string;
}

export interface Plan {
  name: "Plan A" | "Plan B" | "Plan C";
  stance: string;
  timing: string;
  gate: string;
  flightPath: string;
  delay: string;
  fuel: string;
  connections: string;
  groundCrew: string;
  constraints: string;
  reasoning: string;
}

export interface AgentDefinition {
  id: AgentId;
  name: string;
  turnOneOutput: string[];
  turnTwoOutput: string[];
  plans: Plan[];
}

export interface AgentResult {
  status: Status;
  logs: LogEntry[];
  error?: string;
}

export interface ArbitrationResult {
  status: Status;
  logs: LogEntry[];
  error?: string;
  rankedPlans: string[];
  safetyChecks: Record<string, string>;
  finalOutput: Record<string, string>;
}

export type WorkflowEvent =
  | { type: "agent-status"; turn: Turn; agentId: AgentId; status: Status }
  | { type: "agent-log"; turn: Turn; agentId: AgentId; log: LogEntry }
  | { type: "arbitration-status"; status: Status }
  | { type: "arbitration-log"; log: LogEntry }
  | {
      type: "complete";
      result: Pick<
        ArbitrationResult,
        "rankedPlans" | "safetyChecks" | "finalOutput"
      >;
    };

export interface NegotiationService {
  run(scenario: Scenario, signal?: AbortSignal): AsyncIterable<WorkflowEvent>;
}
