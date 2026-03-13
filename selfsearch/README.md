# Selfsearch

LLM-powered calibration model.

## Setup

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API key
OPENROUTER_API_KEY=your-key-here
```

## Commands

```bash
python -m selfsearch.prepare    # Prepare data splits
python -m selfsearch.model val  # Run model on validation set
python -m selfsearch.run_loop   # Evaluate iteration (keep/discard)
```
