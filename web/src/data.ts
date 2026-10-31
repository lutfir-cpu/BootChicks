import type { AgentDefinition, ArbitrationResult, Scenario } from "./types";

export const initialScenario: Scenario = {
  airline: "AS",
  origin: "SFO",
  destination: "LAX",
  disruption: "Late Airport Arrival",
  flight: "AS 136",
};

export const flightRecord = [
  ["Arrival", "—"],
  ["Origin", "—"],
  ["Delay", "—"],
  ["Destination", "LAX"],
];

export const enrichment = [
  ["Resource capacity", "Constrained"],
  ["Runway status", "Active"],
  ["Gate reserve", "Limited"],
  ["Fuel reserve", "5,000 lb"],
  ["Crew duty limit", "8 h 30 min remaining"],
  ["Scheduled arrival", "11:12"],
  ["Weather delay", "5 min"],
  ["Late aircraft delay", "20 min"],
];

const basePlans = [
  {
    name: "Plan A" as const,
    stance: "Preferred",
    timing: "11:27 arrival",
    gate: "Gate 52",
    flightPath: "Direct approach",
    delay: "15 min",
    fuel: "+120 lb",
    connections: "Most protected",
    groundCrew: "Priority turnaround",
    constraints: "Runway separation and fuel reserve satisfied",
    reasoning: "Shortest recoverable delay with a reserved gate.",
  },
  {
    name: "Plan B" as const,
    stance: "Balanced",
    timing: "11:32 arrival",
    gate: "Gate 54",
    flightPath: "Standard arrival",
    delay: "20 min",
    fuel: "+80 lb",
    connections: "Several tight connections",
    groundCrew: "Normal turnaround",
    constraints: "All modeled checks satisfied",
    reasoning: "Trades five minutes for a less constrained gate.",
  },
  {
    name: "Plan C" as const,
    stance: "Concession",
    timing: "11:37 arrival",
    gate: "Gate 56",
    flightPath: "Extended arrival",
    delay: "25 min",
    fuel: "+190 lb",
    connections: "Connections need review",
    groundCrew: "No priority handling",
    constraints: "Fuel margin needs monitoring",
    reasoning: "Preserves surface capacity at the cost of time and fuel.",
  },
];

export const agents: AgentDefinition[] = [
  {
    id: "atc",
    name: "ATC Agent",
    turnOneOutput: [
      "Maintain wake separation on arrival",
      "Confirm runway availability and approach slot",
      "Avoid additional surface congestion",
    ],
    turnTwoOutput: [
      "Arrival sequence checked against runway flow",
      "Gate availability coordinated with ground operations",
    ],
    plans: basePlans.map((plan, index) => ({
      ...plan,
      reasoning: [
        "Uses the earliest safe arrival slot.",
        "Keeps the standard arrival sequence.",
        "Defers arrival to protect runway throughput.",
      ][index],
    })),
  },
  {
    id: "pilot",
    name: "Pilot Agent",
    turnOneOutput: [
      "Protect fuel reserve through approach and taxi",
      "Keep crew duty within the limit",
      "Minimize passenger connection loss",
    ],
    turnTwoOutput: [
      "Fuel burn and crew time compared across options",
      "A direct approach is preferred where cleared",
    ],
    plans: basePlans.map((plan, index) => ({
      ...plan,
      reasoning: [
        "Protects fuel and passenger connections.",
        "Balances fuel margin against delay.",
        "Retains a conservative arrival window.",
      ][index],
    })),
  },
  {
    id: "ground",
    name: "Ground Operations Agent",
    turnOneOutput: [
      "Gate reserve is limited",
      "Protect baggage and turnaround flow",
      "Confirm crew availability for reassignment",
    ],
    turnTwoOutput: [
      "Gate and handling availability confirmed",
      "Turnaround plans matched to each arrival window",
    ],
    plans: basePlans.map((plan, index) => ({
      ...plan,
      reasoning: [
        "Priority team meets the early arrival.",
        "Standard staffing supports Gate 54.",
        "Gate 56 avoids a rushed turnaround.",
      ][index],
    })),
  },
];

export const completedArbitration: Pick<
  ArbitrationResult,
  "rankedPlans" | "safetyChecks" | "finalOutput"
> = {
  rankedPlans: [
    "1. Plan A - ATC / Pilot / Ground",
    "2. Plan B - ATC / Pilot / Ground",
    "3. Plan C - ATC / Pilot / Ground",
  ],
  safetyChecks: {
    "Wake separation": "Satisfied",
    "Fuel reserve": "Above minimum",
    "Runway availability": "Confirmed",
    "Taxiway access": "Available",
    "Gate availability": "Gate 52 reserved",
    "Crew limits": "Within duty limit",
    "Deterministic fallback": "Ready if assignment changes",
  },
  finalOutput: {
    "Selected plan": "Plan A - coordinated early arrival",
    "Overall score": "92 / 100",
    "Selection reasoning":
      "Best delay recovery with all modeled safety checks satisfied.",
    "Revised departure": "No change",
    "Revised arrival": "11:27",
    "Gate assignment": "Gate 52",
    "Flight-plan adjustment": "Direct approach when cleared by ATC",
    "Expected delay reduction": "10 min",
    "Fuel impact": "+120 lb estimated burn",
    "Passenger connections": "Most protected",
    "Ground-crew impact": "Priority turnaround team",
    "Safety status": "All modeled checks satisfied",
    "Main trade-offs": "Priority ground staffing and modest extra fuel burn",
  },
};
