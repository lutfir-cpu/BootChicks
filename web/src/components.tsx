import type {
  AgentDefinition,
  AgentResult,
  ArbitrationResult,
  Plan,
  Scenario,
  Status,
} from "./types";
import { enrichment, flightRecord } from "./data";

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge badge-${status}`}>
      {status[0].toUpperCase() + status.slice(1)}
    </span>
  );
}

export function Header({
  scenario,
  status,
  onTrace,
}: {
  scenario: Scenario;
  status: Status;
  onTrace: () => void;
}) {
  return (
    <header className="topbar">
      <div className="top-inner">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ✈
          </span>
          <span>AeroResolve</span>
        </div>
        <span className={`scenario-status ${status}`} aria-live="polite">
          {scenario.flight} · {scenario.destination} ·{" "}
          {status === "complete"
            ? "Replay complete"
            : status[0].toUpperCase() + status.slice(1)}
        </span>
        <button className="trace-btn" type="button" onClick={onTrace}>
          View Execution Trace
        </button>
      </div>
    </header>
  );
}

function DataFields({ fields }: { fields: string[][] }) {
  return (
    <div className="input-fields">
      {fields.map(([label, value]) => (
        <div className="field" key={label}>
          <span className="field-label">{label}</span>
          <span className="field-value">{value}</span>
        </div>
      ))}
    </div>
  );
}

export function ScenarioInput({
  scenario,
  onChange,
  onRun,
  running,
}: {
  scenario: Scenario;
  onChange: (scenario: Scenario) => void;
  onRun: () => void;
  running: boolean;
}) {
  const update = (key: keyof Scenario, value: string) =>
    onChange({ ...scenario, [key]: value });
  return (
    <section aria-labelledby="input-title">
      <article className="card input-card">
        <div className="input-heading">
          <div>
            <p className="kicker">Input</p>
            <h1 id="input-title">Disruption scenario</h1>
          </div>
          <button
            className="demo-btn"
            type="button"
            onClick={() =>
              onChange({
                airline: "AS",
                origin: "SFO",
                destination: "LAX",
                disruption: "Late Airport Arrival",
                flight: "AS 136",
              })
            }
          >
            Demo
          </button>
        </div>
        <div className="input-columns">
          <div className="input-column">
            <h2>Scenario Controls</h2>
            <div className="field">
              <label htmlFor="airline">Airline</label>
              <select
                id="airline"
                value={scenario.airline}
                onChange={(event) => update("airline", event.target.value)}
              >
                <option value="AS">Alaska Airlines (AS)</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="origin">Origin airport</label>
              <select
                id="origin"
                value={scenario.origin}
                onChange={(event) => update("origin", event.target.value)}
              >
                <option value="SFO">SFO</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="destination">Destination airport</label>
              <select
                id="destination"
                value={scenario.destination}
                onChange={(event) => update("destination", event.target.value)}
              >
                <option value="LAX">LAX</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="disruption">Disruption type</label>
              <select
                id="disruption"
                value={scenario.disruption}
                onChange={(event) => update("disruption", event.target.value)}
              >
                <option>Late Airport Arrival</option>
                <option>Weather Delay</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="flight">Eligible flight</label>
              <select
                id="flight"
                value={scenario.flight}
                onChange={(event) => update("flight", event.target.value)}
              >
                <option>AS 136</option>
              </select>
            </div>
            <div className="field">
              <span className="field-label">Selected flight</span>
              <span className="field-value">{scenario.flight}</span>
            </div>
          </div>
          <div className="input-column">
            <h2>DOT Flight Record</h2>
            <div className="source-row">
              <span className="source-badge">Historical DOT dataset</span>
              <span className="source-badge">2013-2017 data</span>
            </div>
            <DataFields fields={flightRecord} />
          </div>
          <div className="input-column">
            <h2>Simulated Domain Enrichment</h2>
            <div className="source-row">
              <span className="source-badge sim-badge">Simulated inputs</span>
              <span className="source-badge sim-badge">
                Operational assumptions
              </span>
            </div>
            <DataFields fields={enrichment} />
          </div>
        </div>
        <div className="input-footer">
          <button
            className="primary-btn"
            type="button"
            onClick={onRun}
            disabled={running}
          >
            {running ? "Negotiation running…" : "Run Three-Turn Negotiation"}
          </button>
          <p className="note">
            Demonstration replay with simulated operational inputs. No live
            agent service is connected.
          </p>
        </div>
      </article>
    </section>
  );
}

export function LogPanel({
  label,
  logs,
}: {
  label: string;
  logs: AgentResult["logs"];
}) {
  return (
    <div className="panel-block">
      <h4 className="panel-title">Logs</h4>
      <div
        className="logs"
        tabIndex={0}
        aria-label={label}
        role="log"
        aria-live="polite"
      >
        {logs.length ? (
          logs.map((entry, index) => (
            <div className="log-line" key={index}>
              <span>[{entry.time}]</span> {entry.message}
            </div>
          ))
        ) : (
          <span className="empty-value">Waiting for execution trace…</span>
        )}
      </div>
    </div>
  );
}

export function PlanAccordion({ plan }: { plan: Plan }) {
  const fields = [
    ["Revised timing", plan.timing],
    ["Gate assignment", plan.gate],
    ["Flight-plan adjustment", plan.flightPath],
    ["Expected delay", plan.delay],
    ["Fuel impact", plan.fuel],
    ["Passenger connections", plan.connections],
    ["Ground-crew impact", plan.groundCrew],
    ["Constraints", plan.constraints],
    ["Agent reasoning", plan.reasoning],
  ];
  return (
    <details className="plan-row">
      <summary>
        <span>{plan.name}</span>
        <span className="plan-stance">{plan.stance}</span>
      </summary>
      <div className="plan-fields">
        {fields.map(([label, value]) => (
          <DataLine key={label} label={label} value={value} />
        ))}
      </div>
    </details>
  );
}

export function OutputPanel({
  lines,
  plans,
  status,
}: {
  lines: string[];
  plans?: Plan[];
  status: Status;
}) {
  return (
    <div className="output">
      <h4 className="panel-title">Output</h4>
      {status === "complete" ? (
        <>
          <ul className="output-lines">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          {plans?.map((plan) => (
            <PlanAccordion key={plan.name} plan={plan} />
          ))}
        </>
      ) : status === "running" ? (
        <p className="loading">
          <span className="spinner" aria-hidden="true" /> Generating{" "}
          {plans ? "plans" : "output"}…
        </p>
      ) : (
        <p className="empty-value">
          {status === "error"
            ? "Output unavailable."
            : "Output appears after this turn completes."}
        </p>
      )}
    </div>
  );
}

export function AgentCard({
  agent,
  turn,
  result,
}: {
  agent: AgentDefinition;
  turn: 1 | 2;
  result: AgentResult;
}) {
  return (
    <article
      className="card agent-card"
      aria-label={`${agent.name}, Turn ${turn}`}
    >
      <div className="agent-head">
        <h3>{agent.name}</h3>
        <StatusBadge status={result.status} />
      </div>
      <LogPanel label={`${agent.name} Turn ${turn} logs`} logs={result.logs} />
      <OutputPanel
        lines={turn === 1 ? agent.turnOneOutput : agent.turnTwoOutput}
        plans={turn === 2 ? agent.plans : undefined}
        status={result.status}
      />
      {result.error && (
        <p className="error-message" role="alert">
          {result.error}
        </p>
      )}
    </article>
  );
}

export function BranchConnector() {
  return (
    <div className="branch connector" aria-hidden="true">
      <div className="stem" />
      <div className="crossbar" />
      <div className="drop left" />
      <div className="drop center" />
      <div className="drop right" />
    </div>
  );
}
export function LaneConnector() {
  return (
    <div className="lane-connectors connector" aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <div className="lane-line" key={index} />
      ))}
    </div>
  );
}
export function MergeConnector() {
  return (
    <div className="merge connector" aria-hidden="true">
      <div className="merge-line left" />
      <div className="merge-line center" />
      <div className="merge-line right" />
      <div className="bar" />
      <div className="merge-stem" />
    </div>
  );
}

function DataLine({ label, value }: { label: string; value?: string }) {
  return (
    <div className="data-line">
      <span>{label}</span>
      <span className={value ? "" : "empty-value"}>{value || "—"}</span>
    </div>
  );
}

export function FinalArbitrationCard({
  result,
  traceRef,
}: {
  result: ArbitrationResult;
  traceRef: React.RefObject<HTMLDivElement | null>;
}) {
  const complete = result.status === "complete";
  return (
    <article className="card final-card">
      <div className="agent-head">
        <h3>Arbitrator</h3>
        <StatusBadge status={result.status} />
      </div>
      <div ref={traceRef}>
        <LogPanel label="Arbitrator logs" logs={result.logs} />
      </div>
      <div className="output">
        <h4 className="panel-title">Master plan</h4>
        <div className="final-grid">
          <DataLine
            label="Candidate plans received"
            value={complete ? "9" : undefined}
          />
          <DataLine
            label="Ranked candidate plans"
            value={complete ? "3 groups" : undefined}
          />
          <DataLine
            label="Selected plan"
            value={result.finalOutput["Selected plan"]}
          />
          <DataLine
            label="Overall score"
            value={result.finalOutput["Overall score"]}
          />
        </div>
        {complete && (
          <>
            <h4 className="subheading">Ranked plans</h4>
            <ol className="ranked-plans">
              {result.rankedPlans.map((plan) => (
                <li key={plan}>{plan.replace(/^\d+\. /, "")}</li>
              ))}
            </ol>
          </>
        )}
        <h4 className="subheading">Safety checks</h4>
        <div className="final-grid">
          {[
            "Wake separation",
            "Fuel reserve",
            "Runway availability",
            "Taxiway access",
            "Gate availability",
            "Crew limits",
            "Deterministic fallback",
          ].map((label) => (
            <DataLine
              key={label}
              label={label}
              value={result.safetyChecks[label]}
            />
          ))}
        </div>
        <h4 className="subheading">Final output</h4>
        <div className="final-grid">
          {[
            "Selection reasoning",
            "Revised departure",
            "Revised arrival",
            "Gate assignment",
            "Flight-plan adjustment",
            "Expected delay reduction",
            "Fuel impact",
            "Passenger connections",
            "Ground-crew impact",
            "Safety status",
            "Main trade-offs",
          ].map((label) => (
            <DataLine
              key={label}
              label={label}
              value={result.finalOutput[label]}
            />
          ))}
        </div>
        {result.status === "running" && (
          <p className="loading">
            <span className="spinner" aria-hidden="true" /> Evaluating nine
            candidate plans…
          </p>
        )}
        {result.error && (
          <p className="error-message" role="alert">
            {result.error}
          </p>
        )}
      </div>
    </article>
  );
}
