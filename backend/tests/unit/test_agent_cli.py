import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_PATH = PROJECT_ROOT / "agent.py"


def run_agent(question: str) -> dict:
    env = os.environ.copy()
    env["LLM_API_BASE"] = "mock://llm"
    env["LLM_MODEL"] = "mock-model"
    env["LLM_API_KEY"] = "mock-key"
    env["AGENT_API_BASE_URL"] = "mock://api"
    env["LMS_API_KEY"] = "mock-lms-key"
    result = subprocess.run(
        [sys.executable, str(AGENT_PATH), question],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return json.loads(result.stdout)


def test_task1_output_contract_contains_answer_and_tool_calls() -> None:
    data = run_agent("What does REST stand for?")
    assert "answer" in data
    assert "tool_calls" in data
    assert isinstance(data["tool_calls"], list)


def test_task2_merge_conflict_uses_read_file_and_source() -> None:
    data = run_agent("How do you resolve a merge conflict?")
    assert any(tc.get("tool") == "read_file" for tc in data["tool_calls"])
    assert "wiki/git-workflow.md" in data.get("source", "")


def test_task2_wiki_listing_uses_list_files() -> None:
    data = run_agent("What files are in the wiki?")
    assert any(tc.get("tool") == "list_files" for tc in data["tool_calls"])


def test_task3_framework_question_uses_read_file() -> None:
    data = run_agent("What framework does the backend use?")
    assert any(tc.get("tool") == "read_file" for tc in data["tool_calls"])
    assert "fastapi" in data.get("answer", "").lower()


def test_task3_item_count_question_uses_query_api() -> None:
    data = run_agent("How many items are in the database?")
    assert any(tc.get("tool") == "query_api" for tc in data["tool_calls"])
