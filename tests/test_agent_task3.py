"""
Regression tests for Task 3: The System Agent

Tests that agent.py:
1. Uses query_api tool for data questions
2. Uses read_file for source code questions
3. Outputs valid JSON with answer, source, and tool_calls fields
"""

import json
import subprocess
import sys
from pathlib import Path


def run_agent(question: str, timeout: int = 120) -> tuple:
    """
    Run the agent with a question and return the response.

    Args:
        question: The question to ask
        timeout: Timeout in seconds (default 120 for API calls)

    Returns:
        Tuple of (response_dict, stdout, stderr, returncode)
    """
    agent_path = Path(__file__).parent.parent / "agent.py"

    result = subprocess.run(
        ["uv", "run", str(agent_path), question],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    # Parse JSON response
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Failed to parse JSON. Stdout: {result.stdout}", file=sys.stderr)
        raise

    return response, result.stdout, result.stderr, result.returncode


def test_framework_question():
    """
    Test: "What framework does the backend use?"

    Expected:
    - Uses read_file to read backend source code
    - Answer contains "FastAPI"
    - Source references a Python file
    """
    question = "What framework does the backend use?"

    response, stdout, stderr, returncode = run_agent(question)

    # Check exit code
    assert returncode == 0, f"Agent exited with code {returncode}: {stderr}"

    # Check required fields
    assert "answer" in response, "Response missing 'answer' field"
    assert "tool_calls" in response, "Response missing 'tool_calls' field"

    # Check answer is non-empty
    assert len(response["answer"]) > 0, "'answer' must not be empty"

    # Check that read_file was used (not query_api for this question)
    tool_calls = response["tool_calls"]
    tools_used = [tc.get("tool") for tc in tool_calls]
    assert "read_file" in tools_used, f"Expected read_file in tool_calls, got: {tools_used}"

    # Check answer mentions FastAPI
    answer_lower = response["answer"].lower()
    assert "fastapi" in answer_lower, f"Answer should mention FastAPI, got: {response['answer']}"

    print(f"✓ Agent used tools: {tools_used}", file=sys.stderr)
    print(f"✓ Answer: {response['answer'][:100]}...", file=sys.stderr)


def test_database_count_question():
    """
    Test: "How many items are in the database?"

    Expected:
    - Uses query_api with GET /items/
    - Answer contains a number
    - tool_calls contains API response
    """
    question = "How many items are in the database?"

    response, stdout, stderr, returncode = run_agent(question, timeout=120)

    # Check exit code
    assert returncode == 0, f"Agent exited with code {returncode}: {stderr}"

    # Check required fields
    assert "answer" in response, "Response missing 'answer' field"
    assert "tool_calls" in response, "Response missing 'tool_calls' field"

    # Check answer is non-empty
    assert len(response["answer"]) > 0, "'answer' must not be empty"

    # Check that query_api was used
    tool_calls = response["tool_calls"]
    tools_used = [tc.get("tool") for tc in tool_calls]
    assert "query_api" in tools_used, f"Expected query_api in tool_calls, got: {tools_used}"

    # Find the query_api call and check it used correct path
    query_api_calls = [
        tc for tc in tool_calls
        if tc.get("tool") == "query_api"
    ]
    assert len(query_api_calls) > 0, "No query_api tool calls found"

    # Check at least one query_api call used /items/ path
    items_path_found = any(
        "/items/" in str(tc.get("args", {}).get("path", ""))
        for tc in query_api_calls
    )
    assert items_path_found, \
        f"Expected query_api with path containing '/items/', got: {[tc.get('args') for tc in query_api_calls]}"

    # Check answer contains a number
    import re
    numbers = re.findall(r'\d+', response["answer"])
    assert len(numbers) > 0, f"Answer should contain a number, got: {response['answer']}"

    print(f"✓ Agent used tools: {tools_used}", file=sys.stderr)
    print(f"✓ Answer: {response['answer'][:100]}...", file=sys.stderr)


def test_api_status_code_question():
    """
    Test: "What HTTP status code without authentication?"

    Expected:
    - Uses query_api to test the API
    - Answer mentions 401 or 403
    """
    question = "What HTTP status code does the API return when you request /items/ without authentication?"

    response, stdout, stderr, returncode = run_agent(question, timeout=120)

    # Check exit code
    assert returncode == 0, f"Agent exited with code {returncode}: {stderr}"

    # Check required fields
    assert "answer" in response, "Response missing 'answer' field"
    assert "tool_calls" in response, "Response missing 'tool_calls' field"

    # Check answer is non-empty
    assert len(response["answer"]) > 0, "'answer' must not be empty"

    # Check that query_api was used
    tool_calls = response["tool_calls"]
    tools_used = [tc.get("tool") for tc in tool_calls]
    assert "query_api" in tools_used, f"Expected query_api in tool_calls, got: {tools_used}"

    # Check answer mentions 401 or 403 (unauthorized/forbidden)
    answer_lower = response["answer"].lower()
    assert "401" in answer_lower or "403" in answer_lower or "unauthorized" in answer_lower or "forbidden" in answer_lower, \
        f"Answer should mention 401 or 403, got: {response['answer']}"

    print(f"✓ Agent used tools: {tools_used}", file=sys.stderr)
    print(f"✓ Answer: {response['answer'][:100]}...", file=sys.stderr)
