# App screenshots

Captured from the existing Streamlit Arrival desk demo on `feat/mvp`, using offline simulation and bundled synthetic data.
These images show the earlier single-candidate web workflow; the blueprint proposal-board backend is exposed through the CLI/API.
No Claude API requests were made.

## Scenario setup

Default gate-change scenario with editable assumptions and a two-round limit.

![Arrival desk scenario setup](01-scenario-setup.jpg)

## Gate counterproposal

ATC and Pilot accept the first candidate; Ground reports the occupied original gate and proposes G2.

![Ground counterproposal after the gate availability check fails](02-gate-counterproposal.jpg)

## Agreed plan

The second round reaches agreement on landing at minute 20, gate G2, and gate-in at minute 28.
All three roles accept the same validated version.

![Agreed plan with all three role approvals](03-agreed-plan.jpg)

## Fallback recommendation

The same scenario with the round limit reduced to one returns a deterministically validated option without negotiated approval.

![Fallback recommendation with passing mandatory checks](04-fallback-recommendation.jpg)

## Insufficient fuel

The bundled insufficient-fuel scenario rejects the proposed hold and finds no feasible option within the search horizon.

![No feasible plan with the pilot fuel-budget rejection](05-insufficient-fuel.jpg)

## Embed in a PR

Copy the following Markdown into the PR description.

```markdown
### App screenshots

Existing Streamlit demo, offline simulation with synthetic data.
The blueprint proposal-board backend runs through the CLI/API.

![Scenario setup](https://raw.githubusercontent.com/lutfir-cpu/BootChicks/feat/mvp/docs/screenshots/01-scenario-setup.jpg)
![Gate counterproposal](https://raw.githubusercontent.com/lutfir-cpu/BootChicks/feat/mvp/docs/screenshots/02-gate-counterproposal.jpg)
![Agreed plan](https://raw.githubusercontent.com/lutfir-cpu/BootChicks/feat/mvp/docs/screenshots/03-agreed-plan.jpg)
![Fallback recommendation](https://raw.githubusercontent.com/lutfir-cpu/BootChicks/feat/mvp/docs/screenshots/04-fallback-recommendation.jpg)
![Insufficient fuel](https://raw.githubusercontent.com/lutfir-cpu/BootChicks/feat/mvp/docs/screenshots/05-insufficient-fuel.jpg)
```
