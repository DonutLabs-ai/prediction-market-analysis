# Research Outcomes Dashboard

A Next.js application for visualizing prediction market research outcomes and model performance.

## Overview

This dashboard displays:
- Research outcomes from the selfsearch calibration model
- Model performance metrics (composite score, Brier score, ROI, bet rate)
- Iteration history with diffs and metrics
- Interactive charts for tracking improvements

## Data Contract

The dashboard reads data from `public/data/research.json`, which contains:

```json
{
  "iterations": [
    {
      "iteration": 1,
      "composite": 0.456789,
      "brier": 0.189234,
      "roi": 0.0234,
      "pnl": 123.45,
      "num_bets": 456,
      "status": "keep",
      "description": "initial baseline"
    }
  ],
  "best_iteration": {
    "iteration": 5,
    "composite": 0.512345,
    ...
  },
  "total_iterations": 10,
  "kept_iterations": 3,
  "discarded_iterations": 7
}
```

## Getting Started

### Install dependencies

```bash
npm install
```

### Build dashboard data

From the project root:

```bash
python -m scripts.build_dashboard_datasets
```

This generates `public/data/research.json` from `results.tsv`.

### Run development server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to view the dashboard.

## Deployment

The easiest way to deploy is using the [Vercel Platform](https://vercel.com/new).

### Prerequisites

- Ensure `public/data/research.json` contains pre-built data (committed to git)
- Set up automatic data refresh via CI/CD if needed

### Deploy

```bash
vercel deploy --prod
```

## Components

- `app/page.tsx` — Main dashboard page with metrics overview
- `components/ResearchOutcomes.tsx` — Iteration history table and charts
- `public/data/research.json` — Dataset (generated from `results.tsv`)

## Scripts

- `scripts/prepare-data.ts` — TypeScript data preparation utilities
