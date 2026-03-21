---
name: review-ui
description: "Visually inspect the Ledger Flow UI, identify usability, hierarchy, copy, accessibility, and trust issues, and turn them into concrete improvement recommendations. Use when Codex needs to review a running local UI, screenshots, or core routes for polish gaps, UX regressions, confusing flows, or release-readiness feedback, especially when reporting findings back to the user or the project manager."
---

# Review UI

## Overview

Act as a qualitative UI tester for Ledger Flow. Inspect the running app or provided screenshots, identify the most important friction and polish gaps, and convert them into a concise findings report plus a PM-ready priority list.

## Build Context

- Read `README.md`, `AGENT_RULES.md`, `ARCHITECTURE.md`, `TASK.md`, and `ROADMAP.md` before reviewing.
- Use `skills/project-manager/references/ux-quality-bar.md` to align with the current release bar.
- Load [references/ui-review-rubric.md](references/ui-review-rubric.md) when scoring issues or structuring the report.
- Treat Ledger Flow as a consumer-grade finance app for nontechnical users. Default UI language should be about money, accounts, balances, activity, and next steps, not ledger internals.

## Review Workflow

### 1. Define the review target

- Identify which routes, states, or user journey matter for the request.
- Default audit order for broad reviews:
  - `/`
  - `/accounts`
  - `/import`
  - `/unknowns`
  - `/rules`
  - `/transactions`
  - `/setup` when onboarding is in scope
- State any important assumptions: sample data quality, setup shortcuts, device sizes, or flows you could not reach.

### 2. Get eyes on the UI

- Prefer direct inspection of a running UI with whatever browser, screenshot, or image tools are available in the session.
- If the UI is not already running in this repo, start it with:
  - `just app-backend`
  - `just app-frontend`
- If live inspection is unavailable, review provided screenshots.
- Use code reading only as a last fallback, and label any finding from code-only review as inferred rather than observed.

### 3. Exercise real user paths

- Follow the dominant next action on each screen.
- Check both desktop and mobile-width layouts when feasible.
- Deliberately inspect:
  - empty states
  - loading states
  - success feedback
  - validation and error handling
  - keyboard reachability and focus visibility
  - copy that leaks ledger, journal, file-path, or account-wiring implementation details
- Favor first-use clarity and trust over exhaustive interaction coverage.

### 4. Judge what matters

- Prioritize issues that block comprehension, obscure the next action, weaken trust, or make core finance workflows feel tool-like.
- Do not flood the user with minor nits when a smaller set of fixes would materially improve the experience.
- Separate:
  - observed problems
  - likely cause or inference
  - recommendation
- Use the severity rubric and report format in [references/ui-review-rubric.md](references/ui-review-rubric.md).

### 5. Report for two audiences

- Give the user a concise findings report that explains what feels rough, why it matters, and what to improve first.
- Give the project manager a prioritized action list that turns the same findings into scope-aware next steps.
- If the user asks for prioritization, delivery sequencing, or cut/defer guidance, use `$project-manager` alongside this skill.

## Reporting Rules

- Put findings first and order them by severity.
- Cite the route, screen, or screenshot for every finding.
- Mark each item as `Observed` or `Inferred`.
- Recommend the smallest change that fixes the issue well.
- Call out what already works when it helps preserve good decisions.
- End with review limits: routes not checked, states not reached, device coverage not tested, or code-only inferences.

## Quality Bar

- Protect the finance-first posture from `AGENT_RULES.md`.
- Flag UI that makes nontechnical users think about ledgers, journals, file paths, or implementation wiring.
- Prefer one dominant action per screen, sparse secondary actions, clear hierarchy, and trustworthy feedback.
- Treat weak empty, error, loading, and success states as real UX defects, not optional polish.
- Bias toward fewer, higher-confidence findings with concrete recommendations.
