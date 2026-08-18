# TalentGate Frontend

React + Vite single-page app for the TalentGate candidate evaluation platform. See the
[repo-root README](../README.md) for the full project overview, architecture, and setup
instructions covering both this app and the Django backend it talks to.

## Quick start

```bash
npm install
cp .env.example .env   # set VITE_API_BASE_URL if the backend isn't on localhost:8000
npm run dev
```

## Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Start the Vite dev server with HMR |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | ESLint |
