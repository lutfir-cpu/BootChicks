# AeroResolve React dashboard

This Vite React TypeScript app presents the three-turn negotiation as a local demonstration.
It coexists with the Python backend and the older Streamlit interface.

Run `npm install` and `npm run dev` from this folder, then open the address printed by Vite.
Use `npm run format:check`, `npm run lint`, `npm run typecheck`, and `npm run build` to verify it.

`src/types.ts` defines the `NegotiationService` interface and typed workflow events.
`src/mockService.ts` is the current asynchronous replay implementation.
To connect a backend, add a service implementing `NegotiationService.run`, map server events into `WorkflowEvent`, and pass that service to `App` in place of `mockNegotiationService`.
Keep credentials and Claude SDK calls on the server.
The existing Python `/runs` API currently exposes run status and results through polling, so an adapter can poll those endpoints and translate their responses into events.
