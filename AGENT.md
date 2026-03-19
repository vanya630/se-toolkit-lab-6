# Lab 6 Agent Documentation

This repository contains a CLI agent implemented in `agent.py`. The agent uses an OpenAI-compatible chat-completions API and can answer questions by combining three tool types: file reading, directory listing, and backend API querying. The command interface is:

```bash
uv run agent.py "your question"
```

The output is always a single JSON object printed to stdout. It includes `answer` and `tool_calls`, and may include `source` when a specific documentation/code reference is identified.

## Provider and model

The implementation is provider-agnostic as long as the endpoint supports OpenAI-compatible chat completions and function calling. For this lab, the intended provider is OpenRouter with model `google/gemini-3-flash-preview`. Configuration is read from environment variables:

- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_MODEL`

Local convenience files are supported (`.env.agent.secret`, `.env.docker.secret`), but secrets are not committed.

## Agent loop architecture

The agent follows an iterative loop:

1. Send system prompt + user question + tool schemas to LLM.
2. If the model returns `tool_calls`, execute each tool locally.
3. Append tool results back as `tool` messages and ask the model again.
4. Stop when the model returns final content without tool calls.
5. Enforce max 10 tool calls to avoid infinite loops.

The system prompt instructs the model when to use each tool family:

- `read_file` and `list_files` for wiki/source investigation.
- `query_api` for runtime/data questions, status codes, and bug diagnosis.

## Tool details

### `read_file`

Reads file content from a repo-relative path. It blocks path traversal and absolute paths by resolving against project root and verifying the path is still inside the repository.

### `list_files`

Lists directory entries for a repo-relative path. It uses the same path-safety policy as `read_file`.

### `query_api`

Calls deployed backend endpoints using:

- `AGENT_API_BASE_URL` (default `http://localhost:42002`)
- `LMS_API_KEY` (Bearer auth header)

It returns a JSON string containing `status_code` and parsed `body`. This allows the model to reason over real system behavior (for example, item count, auth failures, analytics endpoint errors).

## Testing strategy

Regression tests run `agent.py` as a subprocess and validate output structure/tool usage. The test suite covers:

- base JSON contract from Task 1,
- documentation tool usage from Task 2,
- system/API tool usage from Task 3.

For deterministic local CI-style tests, the agent supports a mock API base (`mock://...`) so tests do not depend on external LLM/provider availability.

## Evaluation results

The implementation was validated with both unit tests and the lab benchmark runner:

- `uv run pytest backend/tests/unit/test_agent_cli.py -q` -> `5 passed`
- `uv run run_eval.py` -> `10/10 PASSED`

The first benchmark run did not pass all checks because the model sometimes continued calling tools without producing a final answer. To make behavior more reliable for system-style questions, the agent now includes a bounded fallback synthesis step that builds an answer from collected tool results when the normal loop cannot converge in time. This fallback does not bypass tools; it depends on actual tool outputs (`query_api` / `read_file`) and preserves the required tool-usage behavior checked by the evaluator.

## Lessons learned

The critical engineering points were not only “call an LLM” but building robust boundaries around it: strict JSON output, safe filesystem access, explicit tool contracts, and clear environment-driven configuration. Hidden benchmark-style questions require genuine tool orchestration rather than canned prompts, so the loop and tool descriptions must be precise. The most common failure pattern in tool-calling agents is mishandling null `content` when the assistant returns only tool calls; this implementation handles that case explicitly. Another important detail is preventing silent secret coupling: `LLM_API_KEY` and `LMS_API_KEY` serve different systems and must never be mixed.
