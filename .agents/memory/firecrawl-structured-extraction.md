---
name: Firecrawl structured extraction
description: How to get structured JSON out of a scraped page without a separate LLM key
---

Firecrawl's v1 API (`POST https://api.firecrawl.dev/v1/scrape`) supports `formats: ["json"]` with `jsonOptions: { prompt, schema }`. Firecrawl runs its own LLM against the scraped page and returns `data.json` already matching the schema — no separate OpenAI/Anthropic key or extra scrape+LLM round trip is needed.

**Why:** Implementation specs that describe a "scrape -> LLM converts to JSON" pipeline can usually be satisfied by Firecrawl's single call, avoiding an extra API dependency and cost.

**How to apply:** When a project needs structured data from a webpage and already has (or is getting) a Firecrawl key, reach for `formats: ["json"]` first before wiring up a separate LLM extraction step.
