#!/usr/bin/env python3
"""
Agent CLI - Task 2: The Documentation Agent

A CLI agent with tools (read_file, list_files) that can navigate
the project wiki and answer questions with source references.

Usage:
    uv run agent.py "How do you resolve a merge conflict?"

Output:
    {
      "answer": "...",
      "source": "wiki/git-workflow.md#resolving-merge-conflicts",
      "tool_calls": [...]
    }
"""

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Maximum number of tool calls per question
MAX_TOOL_CALLS = 10

# System prompt for the documentation agent
SYSTEM_PROMPT = """You are a documentation agent that answers questions about the project by reading its documentation.

You have access to two tools:
1. list_files(path) - List files and directories at a given path
2. read_file(path) - Read the contents of a file

To answer a question:
1. First use list_files("wiki") to discover available documentation files
2. Then use read_file() to read relevant files that might contain the answer
3. Find the exact section that answers the question
4. Provide a concise answer with a source reference

Rules:
- Always use tools before giving a final answer
- Include the source field with the file path and section anchor (e.g., wiki/git.md#merge-conflicts)
- Be concise and accurate
- If you cannot find the answer in the documentation, say so honestly
- Use the tool_calls format when calling tools
"""

# Tool definitions for LLM function calling
TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file from the project repository. Use this to read documentation files in the wiki directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path from project root (e.g., 'wiki/git.md' or 'wiki/git-workflow.md')"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "list_files",
        "description": "List files and directories at a given path. Use this to discover what files exist in a directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path from project root (e.g., 'wiki' or 'docs')"
                }
            },
            "required": ["path"]
        }
    }
]


def load_llm_config() -> dict:
    """
    Load LLM configuration from environment variables.

    Reads from:
    1. Direct environment variables (highest priority)
    2. .env.agent.secret file (for local development)

    Returns:
        dict with keys: LLM_API_KEY, LLM_API_BASE, LLM_MODEL

    Raises:
        SystemExit: If required configuration is missing
    """
    # First, try to load from .env.agent.secret file (local development)
    env_file = Path(__file__).parent / ".env.agent.secret"
    if env_file.exists():
        load_dotenv(env_file)

    # Read from environment variables (works for both local and autochecker)
    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")

    if not api_key:
        print("Error: LLM_API_KEY not found in environment variables", file=sys.stderr)
        sys.exit(1)

    if not api_base:
        print("Error: LLM_API_BASE not found in environment variables", file=sys.stderr)
        sys.exit(1)

    if not model:
        print("Error: LLM_MODEL not found in environment variables", file=sys.stderr)
        sys.exit(1)

    return {
        "api_key": api_key,
        "api_base": api_base,
        "model": model,
    }


def is_safe_path(path: str) -> bool:
    """
    Check if a path is safe (no directory traversal).

    Args:
        path: The path to check

    Returns:
        True if safe, False if path traversal detected
    """
    # Block .. (directory traversal)
    if ".." in path:
        return False
    # Must be relative (no leading /)
    if path.startswith("/"):
        return False
    # No absolute Windows paths
    if len(path) > 1 and path[1] == ":":
        return False
    return True


def resolve_path(path: str) -> Path:
    """
    Resolve a path and verify it's within project root.

    Args:
        path: Relative path from project root

    Returns:
        Absolute Path object

    Raises:
        ValueError: If path traversal detected
    """
    project_root = Path(__file__).parent.resolve()
    full_path = (project_root / path).resolve()

    # Verify path is within project root
    if not str(full_path).startswith(str(project_root)):
        raise ValueError(f"Path traversal detected: {path}")

    return full_path


def read_file(path: str) -> str:
    """
    Read a file from the project repository.

    Args:
        path: Relative path from project root

    Returns:
        File contents as string, or error message
    """
    # Security check
    if not is_safe_path(path):
        return f"Error: Path traversal not allowed: {path}"

    try:
        full_path = resolve_path(path)

        if not full_path.exists():
            return f"Error: File not found: {path}"

        if not full_path.is_file():
            return f"Error: Not a file: {path}"

        return full_path.read_text(encoding="utf-8")

    except Exception as e:
        return f"Error reading file: {e}"


def list_files(path: str) -> str:
    """
    List files and directories at a given path.

    Args:
        path: Relative directory path from project root

    Returns:
        Newline-separated listing, or error message
    """
    # Security check
    if not is_safe_path(path):
        return f"Error: Path traversal not allowed: {path}"

    try:
        full_path = resolve_path(path)

        if not full_path.exists():
            return f"Error: Directory not found: {path}"

        if not full_path.is_dir():
            return f"Error: Not a directory: {path}"

        # List all entries (files and directories)
        entries = []
        for entry in sorted(full_path.iterdir()):
            # Skip hidden files and certain directories
            if entry.name.startswith(".") and entry.name != ".qwen":
                continue
            if entry.name in ("__pycache__", ".venv", ".git", "node_modules"):
                continue

            # Add type indicator
            if entry.is_dir():
                entries.append(f"{entry.name}/")
            else:
                entries.append(entry.name)

        return "\n".join(entries)

    except Exception as e:
        return f"Error listing directory: {e}"


def execute_tool(name: str, args: dict) -> str:
    """
    Execute a tool by name with given arguments.

    Args:
        name: Tool name (read_file or list_files)
        args: Tool arguments dict

    Returns:
        Tool result as string
    """
    if name == "read_file":
        return read_file(args.get("path", ""))
    elif name == "list_files":
        return list_files(args.get("path", ""))
    else:
        return f"Error: Unknown tool: {name}"


def call_llm_with_tools(
    messages: list,
    config: dict,
    tools: list,
    timeout: int = 60
) -> dict:
    """
    Call LLM API with tool definitions.

    Args:
        messages: List of message dicts (role, content)
        config: LLM configuration
        tools: List of tool definitions
        timeout: Request timeout in seconds

    Returns:
        Parsed response dict with message or tool_calls

    Raises:
        SystemExit: If API call fails
    """
    url = f"{config['api_base']}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    payload = {
        "model": config["model"],
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.7,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            return data

    except httpx.TimeoutException:
        print(f"Error: LLM API timeout after {timeout} seconds", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"Error: LLM API returned status {e.response.status_code}", file=sys.stderr)
        print(f"Response: {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Error: Failed to connect to LLM API: {e}", file=sys.stderr)
        sys.exit(1)


def run_agentic_loop(question: str, config: dict) -> tuple:
    """
    Run the agentic loop: call LLM, execute tools, repeat until answer.

    Args:
        question: User's question
        config: LLM configuration

    Returns:
        Tuple of (answer, source, tool_calls_log)
    """
    # Initialize messages with system prompt and user question
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    tool_calls_log = []

    for iteration in range(MAX_TOOL_CALLS):
        # Call LLM with tools
        response = call_llm_with_tools(messages, config, TOOLS)

        # Get the assistant message
        assistant_message = response["choices"][0]["message"]

        # Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])

        if tool_calls:
            # Execute each tool call
            for tool_call in tool_calls:
                # Extract tool info (handle different formats)
                if isinstance(tool_call, dict):
                    function_info = tool_call.get("function", {})
                    tool_name = function_info.get("name", "")
                    tool_args_str = function_info.get("arguments", "{}")

                    try:
                        tool_args = json.loads(tool_args_str) if tool_args_str else {}
                    except json.JSONDecodeError:
                        tool_args = {}

                else:
                    # Handle other formats if needed
                    tool_name = ""
                    tool_args = {}

                # Execute the tool
                result = execute_tool(tool_name, tool_args)

                # Log the tool call
                tool_calls_log.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result
                })

                # Append tool result to messages as tool role
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call]
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", str(len(tool_calls_log))),
                    "content": result
                })

            # Continue loop to get next LLM response
            continue

        else:
            # No tool calls - this is the final answer
            answer = assistant_message.get("content", "")

            # Try to extract source from the answer
            source = extract_source(answer)

            return answer, source, tool_calls_log

    # Max iterations reached
    answer = "I reached the maximum number of tool calls (10). Based on the information gathered, I cannot provide a complete answer."
    source = ""

    return answer, source, tool_calls_log


def extract_source(answer: str) -> str:
    """
    Try to extract a source reference from the answer.

    Looks for patterns like:
    - wiki/file.md#section
    - wiki/file.md
    - docs/file.md

    Args:
        answer: The LLM's answer text

    Returns:
        Source reference string, or empty if not found
    """
    import re

    # Look for wiki/file.md#section pattern
    pattern = r'(wiki/[\w-]+\.md(?:#[\w-]+)?)'
    match = re.search(pattern, answer)

    if match:
        return match.group(1)

    # Look for docs/file.md pattern
    pattern = r'(docs/[\w-]+\.md(?:#[\w-]+)?)'
    match = re.search(pattern, answer)

    if match:
        return match.group(1)

    return ""


def format_response(answer: str, source: str, tool_calls: list) -> dict:
    """
    Build the structured JSON response.

    Args:
        answer: The final answer
        source: Source reference (file.md#section)
        tool_calls: List of tool call logs

    Returns:
        dict with answer, source, and tool_calls fields
    """
    return {
        "answer": answer,
        "source": source,
        "tool_calls": tool_calls,
    }


def main():
    """
    Main entry point for the agent CLI.

    Usage: agent.py "your question"

    Outputs valid JSON to stdout.
    All errors go to stderr.
    Exit code 0 on success, 1 on error.
    """
    # Check for question argument
    if len(sys.argv) < 2:
        print("Error: Missing question argument", file=sys.stderr)
        print('Usage: uv run agent.py "your question"', file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Load LLM configuration
    config = load_llm_config()

    # Run the agentic loop
    answer, source, tool_calls = run_agentic_loop(question, config)

    # Format and output the response
    response = format_response(answer, source, tool_calls)

    # Output valid JSON to stdout (single line)
    print(json.dumps(response, ensure_ascii=False))

    sys.exit(0)


if __name__ == "__main__":
    main()
