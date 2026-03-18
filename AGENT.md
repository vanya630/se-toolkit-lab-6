# Agent — Task 2: The Documentation Agent

## Overview

This agent extends Task 1 with **tools** and an **agentic loop**. It can now:
- Use `read_file` to read documentation files
- Use `list_files` to discover wiki structure
- Loop: call LLM → execute tools → feed results → repeat until answer
- Provide source references with answers

## Architecture

### Agentic Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agentic Loop                               │
│                                                                 │
│  User Question: "How do you resolve a merge conflict?"          │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  1. Send to LLM with tool definitions                     │  │
│  │     - System prompt                                       │  │
│  │     - User question                                       │  │
│  │     - Tools: read_file, list_files                        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  2. LLM responds with tool_calls                          │  │
│  │     - list_files(path="wiki")                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  3. Execute tool, get result                              │  │
│  │     - Result: "git-workflow.md\ngit.md\n..."              │  │
│  │     - Append to messages as tool role                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  4. Call LLM again with tool results                      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  5. LLM responds with more tool_calls                     │  │
│  │     - read_file(path="wiki/git-workflow.md")              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  6. Execute, append, repeat...                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  7. LLM responds with final answer (no tool_calls)        │  │
│  │     - Extract answer and source                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            ↓                                    │
│  Output JSON: {answer, source, tool_calls}                      │
└─────────────────────────────────────────────────────────────────┘
```

### Components

```
┌──────────────────────────────────────────────────────────────┐
│                     agent.py                                 │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Tools                                                  │  │
│  │  - read_file(path) — Read file contents                 │  │
│  │  - list_files(path) — List directory                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Agentic Loop                                           │  │
│  │  - call_llm_with_tools() — LLM API with functions       │  │
│  │  - run_agentic_loop() — Execute tools, iterate          │  │
│  │  - MAX_TOOL_CALLS = 10 — Safety limit                   │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Security                                               │  │
│  │  - is_safe_path() — Block path traversal (..)           │  │
│  │  - resolve_path() — Verify within project root          │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                            │
                            │ HTTP POST /v1/chat/completions
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              Qwen Code API (on VM)                           │
│         http://10.93.26.121:8080/v1                          │
└──────────────────────────────────────────────────────────────┘
```

## Tools

### read_file

Read a file from the project repository.

**Schema:**
```json
{
  "name": "read_file",
  "description": "Read a file from the project repository",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Relative path from project root"
      }
    },
    "required": ["path"]
  }
}
```

**Example:**
```python
read_file("wiki/git-workflow.md")
# Returns: "## Merge Conflicts\n...\n"
```

**Security:**
- Blocks `..` in paths (directory traversal prevention)
- Only allows relative paths (no leading `/`)
- Verifies resolved path is within project root
- Returns error message for invalid paths

---

### list_files

List files and directories at a given path.

**Schema:**
```json
{
  "name": "list_files",
  "description": "List files and directories at a given path",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Relative directory path from project root"
      }
    },
    "required": ["path"]
  }
}
```

**Example:**
```python
list_files("wiki")
# Returns: "git-workflow.md\ngit.md\nssh.md\n..."
```

**Security:**
- Same path validation as `read_file`
- Skips hidden files (except `.qwen`)
- Skips common noise directories (`__pycache__`, `.venv`, etc.)

---

## Agentic Loop

### Implementation

```python
def run_agentic_loop(question: str, config: dict) -> tuple:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]
    
    tool_calls_log = []
    
    for iteration in range(MAX_TOOL_CALLS):  # Max 10 calls
        # 1. Call LLM with tools
        response = call_llm_with_tools(messages, config, TOOLS)
        assistant_message = response["choices"][0]["message"]
        
        # 2. Check for tool calls
        tool_calls = assistant_message.get("tool_calls", [])
        
        if tool_calls:
            # 3. Execute each tool
            for tool_call in tool_calls:
                result = execute_tool(tool_name, tool_args)
                
                # 4. Log and append result
                tool_calls_log.append({...})
                messages.append({"role": "tool", "content": result})
            
            # 5. Continue loop
            continue
        else:
            # 6. Final answer
            answer = assistant_message.get("content", "")
            source = extract_source(answer)
            return answer, source, tool_calls_log
    
    # Max iterations reached
    return "Max tool calls reached", "", tool_calls_log
```

### Flow

1. **Initialize** messages with system prompt + user question
2. **Call LLM** with tool definitions
3. **Parse response:**
   - Has `tool_calls`? → Execute tools, append results, go to step 2
   - Has `content` only? → Final answer, exit loop
4. **Max 10 iterations** to prevent infinite loops
5. **Return** answer, source, and tool_calls log

---

## System Prompt

```python
SYSTEM_PROMPT = """
You are a documentation agent that answers questions about the project 
by reading its documentation.

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
- Include the source field with the file path and section anchor
- Be concise and accurate
- If you cannot find the answer in the documentation, say so honestly
"""
```

### Strategy

The system prompt instructs the LLM to:
1. **Discover** wiki structure with `list_files("wiki")`
2. **Read** relevant files with `read_file()`
3. **Find** the exact section with the answer
4. **Reference** the source (e.g., `wiki/git.md#merge-conflicts`)

---

## Usage

### Basic Usage

```bash
# Ask a documentation question
uv run agent.py "How do you resolve a merge conflict?"
```

### Example Output

```json
{
  "answer": "To resolve a merge conflict: 1) Open the conflicting file, 2) Look for conflict markers (<<<<<<, ======, >>>>>>), 3) Edit to keep desired changes, 4) Remove conflict markers, 5) Stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {
      "tool": "list_files",
      "args": {"path": "wiki"},
      "result": "git-workflow.md\ngit.md\nssh.md\n..."
    },
    {
      "tool": "read_file",
      "args": {"path": "wiki/git-workflow.md"},
      "result": "## Resolving Merge Conflicts\nWhen you encounter a merge conflict..."
    }
  ]
}
```

### Output Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `answer` | string | ✅ | The final answer |
| `source` | string | ✅ | Wiki reference (file.md#section) |
| `tool_calls` | array | ✅ | All tool calls made (populated when tools used) |

### Tool Call Format

Each entry in `tool_calls`:
```json
{
  "tool": "read_file",
  "args": {"path": "wiki/git-workflow.md"},
  "result": "File contents here..."
}
```

---

## Configuration

### Environment Variables

Same as Task 1, reads from `.env.agent.secret`:

```bash
LLM_API_KEY=your-api-key
LLM_API_BASE=http://10.93.26.121:8080/v1
LLM_MODEL=qwen3-coder-plus
```

---

## Testing

### Run Tests

```bash
# Run Task 2 tests
uv run pytest tests/test_agent_task2.py -v

# Run all agent tests
uv run pytest tests/test_agent*.py -v
```

### Test Cases

| Test | Question | Expected Tools | Expected Source |
|------|----------|----------------|-----------------|
| `test_merge_conflict_question` | "How do you resolve a merge conflict?" | `read_file` | `wiki/git-workflow.md#...` |
| `test_wiki_files_question` | "What files are in the wiki?" | `list_files` | (any wiki reference) |
| `test_tool_security_path_traversal` | "What is REST?" | (any) | (any) |

### Test Assertions

**Merge Conflict Test:**
- ✅ Exit code 0
- ✅ `answer` field non-empty
- ✅ `source` field exists
- ✅ `tool_calls` populated
- ✅ `read_file` in tools used
- ✅ Source references wiki file

**Wiki Files Test:**
- ✅ Exit code 0
- ✅ `answer` field non-empty
- ✅ `tool_calls` populated
- ✅ `list_files` in tools used
- ✅ `list_files` called with `path="wiki"`

---

## Security

### Path Traversal Prevention

```python
def is_safe_path(path: str) -> bool:
    if ".." in path:
        return False
    if path.startswith("/"):
        return False
    if len(path) > 1 and path[1] == ":":
        return False  # Windows absolute path
    return True
```

### Path Resolution

```python
def resolve_path(path: str) -> Path:
    project_root = Path(__file__).parent.resolve()
    full_path = (project_root / path).resolve()
    
    # Verify within project root
    if not str(full_path).startswith(str(project_root)):
        raise ValueError(f"Path traversal detected: {path}")
    
    return full_path
```

### What's Blocked

| Attack | Example | Blocked? |
|--------|---------|----------|
| Parent directory | `../secret.txt` | ✅ Yes |
| Absolute path | `/etc/passwd` | ✅ Yes |
| Windows path | `C:\Windows\...` | ✅ Yes |
| Nested traversal | `wiki/../../secret.txt` | ✅ Yes |

---

## File Structure

```
se-toolkit-lab-6/
├── agent.py                 # Main CLI agent (Task 2 version)
├── .env.agent.secret        # LLM configuration
├── plans/
│   ├── task-1.md           # Task 1 plan
│   └── task-2.md           # Task 2 plan
├── tests/
│   ├── test_agent_task1.py # Task 1 tests
│   └── test_agent_task2.py # Task 2 tests
└── AGENT.md                # This documentation
```

---

## Troubleshooting

### "LLM_API_KEY not found"

**Fix:** Ensure `.env.agent.secret` exists with valid API key.

### "Max tool calls reached"

**Problem:** LLM is calling too many tools before answering.

**Fix:** 
- Check system prompt encourages concise tool use
- Verify LLM model supports function calling well

### "Path traversal detected"

**Problem:** Tool tried to access file outside project root.

**Fix:** This is a security feature. The path should be within the project.

### Tool calls not populated

**Problem:** LLM not using tools.

**Fix:**
- Check system prompt includes tool instructions
- Verify tool definitions are correct
- Try a question that clearly requires documentation lookup

---

## Next Steps (Task 3)

In Task 3, you'll extend this agent with:
- **Domain knowledge:** Backend API, database schema
- **More tools:** `query_api()` to fetch live data
- **Complex reasoning:** Multi-step questions
- **Better source extraction:** Section anchors, line numbers

---

## License

Part of the Software Engineering Toolkit course at Innopolis University.
