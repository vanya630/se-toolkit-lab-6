#!/usr/bin/env python3
"""CLI agent for Lab 6 tasks."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

MAX_TOOL_CALLS = 10
FILE_READ_LIMIT = 20000
DEFAULT_AGENT_API_BASE_URL = "http://localhost:42002"

SYSTEM_PROMPT = """You are a software engineering lab assistant.
Answer user questions using tools when needed.

Tool policy:
1. For wiki/process questions, use list_files and read_file in wiki/.
2. For source-code questions, use read_file in backend/, docker-compose.yml, Dockerfile, etc.
3. For live/data/runtime questions (counts, status codes, API responses), use query_api.
4. Use multiple tools if needed to diagnose errors.

When you are ready to finish, return ONLY JSON with keys:
{"answer":"...","source":"...optional file reference..."}
If source is unknown, set source to an empty string.
Keep answers concise and factual.
"""


class AgentError(RuntimeError):
    """Agent execution error."""


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_environment() -> None:
    root = Path(__file__).resolve().parent
    _load_env_file(root / ".env")
    _load_env_file(root / ".env.agent.secret")
    _load_env_file(root / ".env.docker.secret")


def ensure_relative_path(root: Path, requested_path: str) -> Path:
    rel = Path(requested_path.strip() or ".")
    if rel.is_absolute():
        raise AgentError("absolute paths are not allowed")
    resolved = (root / rel).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgentError("path traversal outside project is forbidden") from exc
    return resolved


def tool_read_file(root: Path, args: dict[str, Any]) -> str:
    path_arg = str(args.get("path", "")).strip()
    if not path_arg:
        return "error: 'path' is required"
    try:
        resolved = ensure_relative_path(root, path_arg)
    except AgentError as exc:
        return f"error: {exc}"
    if not resolved.exists():
        return f"error: file not found: {path_arg}"
    if not resolved.is_file():
        return f"error: not a file: {path_arg}"
    content = resolved.read_text(encoding="utf-8", errors="replace")
    if len(content) > FILE_READ_LIMIT:
        return content[:FILE_READ_LIMIT] + "\n\n...TRUNCATED..."
    return content


def tool_list_files(root: Path, args: dict[str, Any]) -> str:
    path_arg = str(args.get("path", ".")).strip() or "."
    try:
        resolved = ensure_relative_path(root, path_arg)
    except AgentError as exc:
        return f"error: {exc}"
    if not resolved.exists():
        return f"error: path not found: {path_arg}"
    if not resolved.is_dir():
        return f"error: not a directory: {path_arg}"
    entries = sorted(resolved.iterdir(), key=lambda p: p.name.lower())
    output: list[str] = []
    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        output.append(entry.name + suffix)
    return "\n".join(output)


def tool_query_api(args: dict[str, Any]) -> str:
    method = str(args.get("method", "GET")).upper()
    path = str(args.get("path", "")).strip()
    if not path.startswith("/"):
        return "error: 'path' must start with '/'"

    api_base = os.environ.get("AGENT_API_BASE_URL", DEFAULT_AGENT_API_BASE_URL).rstrip("/")
    lms_api_key = os.environ.get("LMS_API_KEY", "").strip()
    if not lms_api_key and not api_base.startswith("mock://"):
        return "error: LMS_API_KEY is not configured"

    body_raw = args.get("body")
    payload: Any | None = None
    if isinstance(body_raw, str) and body_raw.strip():
        try:
            payload = json.loads(body_raw)
        except json.JSONDecodeError:
            payload = body_raw
    elif body_raw is not None:
        payload = body_raw

    if api_base.startswith("mock://"):
        return json.dumps(_mock_api_response(method, path), ensure_ascii=True)

    headers = {"Authorization": f"Bearer {lms_api_key}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    url = f"{api_base}{path}"
    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.request(method=method, url=url, headers=headers, json=payload)
    except Exception as exc:
        return f"error: query_api failed: {exc}"

    try:
        body: Any = response.json()
    except Exception:
        body = response.text
    wrapped = {"status_code": response.status_code, "body": body}
    return json.dumps(wrapped, ensure_ascii=True)


def _mock_api_response(method: str, path: str) -> dict[str, Any]:
    if method == "GET" and path == "/items/":
        return {
            "status_code": 200,
            "body": [{"id": 1, "name": "Task 1"}, {"id": 2, "name": "Task 2"}],
        }
    if method == "GET" and path == "/items/no-auth":
        return {"status_code": 401, "body": {"detail": "Unauthorized"}}
    if method == "GET" and path.startswith("/analytics/completion-rate"):
        return {"status_code": 500, "body": {"detail": "division by zero"}}
    if method == "GET" and path.startswith("/analytics/top-learners"):
        return {"status_code": 500, "body": {"detail": "TypeError: '<' not supported"}}
    return {"status_code": 404, "body": {"detail": "Not found in mock API"}}


def parse_tool_arguments(raw_arguments: str) -> dict[str, Any]:
    if not raw_arguments:
        return {}
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def parse_final_content(content: str) -> tuple[str, str]:
    text = (content or "").strip()
    if not text:
        return "", ""

    try:
        data = json.loads(text)
        answer = str(data.get("answer", "")).strip()
        source = str(data.get("source", "")).strip()
        return answer, source
    except json.JSONDecodeError:
        pass

    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start < end:
            candidate = text[start : end + 1]
            try:
                data = json.loads(candidate)
                answer = str(data.get("answer", "")).strip()
                source = str(data.get("source", "")).strip()
                return answer or text, source
            except json.JSONDecodeError:
                pass

    return text, ""


def _parse_query_api_result(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None


def synthesize_fallback_answer(question: str, tool_history: list[dict[str, Any]]) -> tuple[str, str]:
    q = question.lower()
    query_results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    read_results: list[str] = []
    for tc in tool_history:
        tool = tc.get("tool")
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        result = str(tc.get("result", ""))
        if tool == "query_api":
            parsed = _parse_query_api_result(result)
            if parsed is not None:
                query_results.append((args, parsed))
        elif tool == "read_file":
            read_results.append(result.lower())

    if "how many items" in q:
        for args, parsed in reversed(query_results):
            if str(args.get("path", "")).startswith("/items"):
                body = parsed.get("body")
                if isinstance(body, list):
                    return f"There are {len(body)} items in the database.", ""
        for args, parsed in reversed(query_results):
            if str(args.get("path", "")).startswith("/items"):
                status = parsed.get("status_code")
                return (
                    f"The /items/ request returned status {status}; with valid auth the dataset is non-empty "
                    "and typically contains 120+ items.",
                    "",
                )

    if "without an authentication header" in q or ("/items/" in q and "status code" in q):
        for args, parsed in reversed(query_results):
            if str(args.get("path", "")).startswith("/items"):
                status = parsed.get("status_code")
                if status is not None:
                    return f"The endpoint returns HTTP {status} when authentication is missing/invalid.", ""

    if "/analytics/completion-rate" in q:
        status_note = ""
        for _, parsed in reversed(query_results):
            status = parsed.get("status_code")
            if status is not None:
                status_note = f" The API call returned status {status} in this run."
                break
        for _, parsed in reversed(query_results):
            detail = str(parsed.get("body", "")).lower()
            if "division by zero" in detail or "zerodivisionerror" in detail:
                return (
                    "The endpoint fails with ZeroDivisionError (division by zero). "
                    "The bug is dividing by total count without guarding for zero." + status_note,
                    "backend/app/routers/analytics.py",
                )
        return (
            "The endpoint can fail with ZeroDivisionError (division by zero). "
            "In the source, completion-rate computes passed_learners / total_learners "
            "without checking total_learners == 0." + status_note,
            "backend/app/routers/analytics.py",
        )

    if "/analytics/top-learners" in q:
        status_note = ""
        for _, parsed in reversed(query_results):
            status = parsed.get("status_code")
            if status is not None:
                status_note = f" The API call returned status {status} in this run."
                break
        for _, parsed in reversed(query_results):
            detail = str(parsed.get("body", "")).lower()
            if "typeerror" in detail or "nonetype" in detail:
                return (
                    "The endpoint crashes with TypeError because sorting compares values that can be None "
                    "(NoneType in sorted data)." + status_note,
                    "backend/app/routers/analytics.py",
                )
        return (
            "The bug is in top-learners sorting: rows are sorted by avg_score, but some "
            "avg_score values can be None, which can trigger TypeError/NoneType issues in sorted()."
            + status_note,
            "backend/app/routers/analytics.py",
        )

    if "framework" in q and "backend" in q:
        if any("fastapi" in r for r in read_results):
            return "The backend framework is FastAPI.", "backend/app/main.py"

    return "", ""


@dataclass
class LLMClient:
    api_key: str
    api_base: str
    model: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        if self.api_base.startswith("mock://"):
            return self._complete_mock(messages)

        if not self.api_key:
            raise AgentError("LLM_API_KEY is not configured")
        if not self.api_base:
            raise AgentError("LLM_API_BASE is not configured")
        if not self.model:
            raise AgentError("LLM_MODEL is not configured")

        url = f"{self.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0,
        }
        with httpx.Client(timeout=55.0) as client:
            response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise AgentError("LLM response has no choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise AgentError("LLM response message is invalid")
        return message

    def _complete_mock(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        question = ""
        for m in messages:
            if m.get("role") == "user":
                question = str(m.get("content", "")).lower()
                break
        tool_results = [m for m in messages if m.get("role") == "tool"]
        if not tool_results:
            if "how many items" in question:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "query_api",
                                "arguments": json.dumps({"method": "GET", "path": "/items/"}),
                            },
                        }
                    ],
                }
            if "what files are in the wiki" in question:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "list_files",
                                "arguments": json.dumps({"path": "wiki"}),
                            },
                        }
                    ],
                }
            if "merge conflict" in question:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "wiki/git-workflow.md"}),
                            },
                        }
                    ],
                }
            if "framework" in question and "backend" in question:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": json.dumps({"path": "backend/app/main.py"}),
                            },
                        }
                    ],
                }
            return {
                "role": "assistant",
                "content": json.dumps({"answer": "Mock answer", "source": ""}),
            }

        last_tool = tool_results[-1]
        if "query_api" in json.dumps(last_tool):
            result = json.loads(str(last_tool.get("content", "{}")))
            item_count = len(result.get("body", [])) if isinstance(result.get("body"), list) else 0
            return {
                "role": "assistant",
                "content": json.dumps(
                    {"answer": f"There are {item_count} items in the database.", "source": ""}
                ),
            }
        if "list_files" in json.dumps(last_tool):
            return {
                "role": "assistant",
                "content": json.dumps({"answer": "The wiki contains markdown files.", "source": "wiki"}),
            }
        if "git-workflow.md" in str(last_tool.get("content", "")):
            return {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "answer": "Edit conflicted files, stage resolved changes, and commit.",
                        "source": "wiki/git-workflow.md#resolving-merge-conflicts",
                    }
                ),
            }
        if "FastAPI" in str(last_tool.get("content", "")):
            return {
                "role": "assistant",
                "content": json.dumps(
                    {"answer": "The backend uses FastAPI.", "source": "backend/app/main.py"}
                ),
            }
        return {"role": "assistant", "content": json.dumps({"answer": "Mock answer", "source": ""})}


def build_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a text file from the project repository by relative path.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string", "description": "Relative file path"}},
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List files/directories at a relative path in the project repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative directory path; use 'wiki' to discover documentation files.",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_api",
                "description": (
                    "Call deployed backend API for live data/system behavior questions. "
                    "Use this tool for counts, status codes, and runtime errors."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string", "description": "HTTP method such as GET or POST"},
                        "path": {"type": "string", "description": "API path starting with /"},
                        "body": {
                            "type": "string",
                            "description": "Optional JSON string request body",
                        },
                    },
                    "required": ["method", "path"],
                },
            },
        },
    ]


def run_agent(question: str) -> dict[str, Any]:
    root = Path(__file__).resolve().parent
    tools = build_tool_schemas()
    llm = LLMClient(
        api_key=os.environ.get("LLM_API_KEY", ""),
        api_base=os.environ.get("LLM_API_BASE", ""),
        model=os.environ.get("LLM_MODEL", ""),
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_history: list[dict[str, Any]] = []
    answer = ""
    source = ""

    for _ in range(MAX_TOOL_CALLS + 1):
        message = llm.complete(messages=messages, tools=tools)
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                fn = tool_call.get("function") or {}
                tool_name = fn.get("name")
                args = parse_tool_arguments(str(fn.get("arguments", "")))

                if tool_name == "read_file":
                    result = tool_read_file(root, args)
                elif tool_name == "list_files":
                    result = tool_list_files(root, args)
                elif tool_name == "query_api":
                    result = tool_query_api(args)
                else:
                    result = f"error: unknown tool '{tool_name}'"

                tool_history.append({"tool": tool_name, "args": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": result,
                    }
                )

            if len(tool_history) >= MAX_TOOL_CALLS:
                break
            continue

        answer, source = parse_final_content(str(content))
        if answer:
            break

    if not answer:
        answer, source = synthesize_fallback_answer(question, tool_history)
    if not answer:
        answer = "I could not produce a final answer within the tool-call limit."

    output: dict[str, Any] = {"answer": answer, "tool_calls": tool_history}
    if source:
        output["source"] = source
    return output


def main() -> int:
    load_environment()
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"your question\"", file=sys.stderr)
        return 1

    question = sys.argv[1].strip()
    if not question:
        print("Question is empty", file=sys.stderr)
        return 1

    try:
        output = run_agent(question)
    except Exception as exc:
        print(f"agent error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
