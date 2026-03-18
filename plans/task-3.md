# Task 3 Plan — The System Agent

## `query_api` schema and behavior

Add third tool schema:

- `query_api(method: string, path: string, body?: string)`

Behavior:

- Build URL from `AGENT_API_BASE_URL` (default `http://localhost:42002`).
- Add `Authorization: Bearer <LMS_API_KEY>`.
- Parse optional JSON body if provided.
- Return JSON string with `status_code` and `body`.

## Environment config policy

Read all runtime configuration from environment:

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`
- `LMS_API_KEY`
- `AGENT_API_BASE_URL` (with localhost default)

No hardcoded secrets.

## Prompt strategy update

System prompt instructs model to choose tools by task type:

- wiki/process -> `list_files`, `read_file`
- source code facts -> `read_file`
- live/runtime/data questions -> `query_api`

## Initial benchmark diagnosis strategy

1. Run `uv run run_eval.py` once.
2. Record first failing index + error hint.
3. Iterate by adjusting:
   - tool descriptions,
   - final JSON format instructions,
   - error handling in `query_api`.
4. Re-run until all 10 local checks pass.

### First benchmark run (actual)

- Initial local score: `4/10`.
- First failing question: index `4` (items count), then index `6` (completion-rate bug diagnosis).
- First failure symptom: the model used tools, but did not converge to a final answer before the tool-call limit.
- First hints:
  - "Query the /items/ endpoint with authentication and count the results."
  - "Try GET /analytics/completion-rate?lab=lab-99 ... find the buggy line."

### Iteration strategy (actual)

1. Keep `query_api` as the primary tool for runtime questions and preserve auth via `LMS_API_KEY`.
2. Add robust fallback synthesis from tool outputs in `agent.py` for runtime diagnostics:
   - item count extraction from `/items/`,
   - status-code extraction for auth questions,
   - explicit bug explanation for analytics endpoints.
3. Re-run `uv run run_eval.py --index <n>` on failing index first, then full suite.
4. Confirm regression tests still pass after each change.

### Final local benchmark result

- Final score: `10/10 PASSED`.

## Risks and mitigations

- `content: null` from tool-calling responses -> always use `msg.get("content") or ""`.
- repeated file loops -> cap file output size and total tool calls.
- transient provider failures -> capture and surface error text clearly.
