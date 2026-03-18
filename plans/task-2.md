# Task 2 Plan: The Documentation Agent

## Overview

Extend the Task 1 agent with **tools** and an **agentic loop**. The agent can now:
1. Use `read_file` to read files from the project
2. Use `list_files` to discover wiki structure
3. Loop: call LLM → execute tools → feed results → repeat until answer

## Architecture

### Agentic Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agentic Loop                               │
│                                                                 │
│  1. Send question + tool definitions to LLM                     │
│  2. LLM responds with tool_calls OR final answer                │
│  3. If tool_calls:                                              │
│     a. Execute each tool (read_file, list_files)                │
│     b. Append results as tool role messages                     │
│     c. Go to step 1                                             │
│  4. If final answer:                                            │
│     a. Extract answer and source                                │
│     b. Output JSON and exit                                     │
│  5. If 10 tool calls reached: stop and use current answer       │
└─────────────────────────────────────────────────────────────────┘
```

### Data Flow

```
User Question
      ↓
┌─────────────────────────────────────────────────────────────┐
│  Loop (max 10 iterations)                                   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  1. Build messages array with:                        │  │
│  │     - System prompt (with tool definitions)           │  │
│  │     - User question                                   │  │
│  │     - Previous tool results (if any)                  │  │
│  └───────────────────────────────────────────────────────┘  │
│                            ↓                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  2. Call LLM API                                      │  │
│  └───────────────────────────────────────────────────────┘  │
│                            ↓                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  3. Parse response                                    │  │
│  │     - Has tool_calls? → Execute tools, continue loop  │  │
│  │     - Has message? → Final answer, exit loop          │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
      ↓
JSON Output: {answer, source, tool_calls}
```

## Tool Definitions

### read_file

**Purpose:** Read contents of a file from the project repository.

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
        "description": "Relative path from project root (e.g., 'wiki/git.md')"
      }
    },
    "required": ["path"]
  }
}
```

**Implementation:**
```python
def read_file(path: str) -> str:
    # Security: prevent path traversal (no ../)
    # Read file from project root
    # Return contents or error message
```

**Security:**
- Block `..` in paths (prevent directory traversal)
- Only allow paths within project root
- Handle missing files gracefully

---

### list_files

**Purpose:** List files and directories at a given path.

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
        "description": "Relative directory path from project root (e.g., 'wiki')"
      }
    },
    "required": ["path"]
  }
}
```

**Implementation:**
```python
def list_files(path: str) -> str:
    # Security: prevent path traversal
    # List directory contents
    # Return newline-separated listing
```

**Security:**
- Block `..` in paths
- Only allow directories within project root
- Handle missing directories gracefully

---

## System Prompt Strategy

The system prompt will instruct the LLM to:

1. **Use tools strategically:**
   - Start with `list_files("wiki")` to discover available documentation
   - Use `read_file("wiki/<topic>.md")` to find specific information
   - Include source references in the final answer

2. **Format tool calls correctly:**
   - Use the function calling format expected by the LLM
   - Include tool name and arguments

3. **Provide source references:**
   - Always include the file path and section anchor in the answer
   - Format: `wiki/git-workflow.md#resolving-merge-conflicts`

### Example System Prompt

```
You are a documentation agent that answers questions about the project.

You have access to two tools:
- list_files(path): List files in a directory
- read_file(path): Read contents of a file

To answer a question:
1. First use list_files("wiki") to discover available documentation
2. Then use read_file() to read relevant files
3. Find the exact section that answers the question
4. Provide the answer with a source reference (file.md#section)

Rules:
- Always include the source field with file path and section anchor
- Use tools before giving a final answer
- Be concise and accurate
```

---

## Output Format

### Success Response

```json
{
  "answer": "Edit the conflicting file, choose which changes to keep, then stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {
      "tool": "list_files",
      "args": {"path": "wiki"},
      "result": "git-workflow.md\ngit.md\n..."
    },
    {
      "tool": "read_file",
      "args": {"path": "wiki/git-workflow.md"},
      "result": "## Resolving Merge Conflicts\n..."
    }
  ]
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `answer` | string | ✅ | The final answer |
| `source` | string | ✅ | Wiki reference (file.md#section) |
| `tool_calls` | array | ✅ | All tool calls made (may be empty) |

---

## Implementation Details

### Tool Registry

```python
TOOLS = [
    {
        "name": "read_file",
        "description": "...",
        "parameters": {...}
    },
    {
        "name": "list_files",
        "description": "...",
        "parameters": {...}
    }
]

def execute_tool(name: str, args: dict) -> str:
    if name == "read_file":
        return read_file(args["path"])
    elif name == "list_files":
        return list_files(args["path"])
```

### Agentic Loop

```python
def run_agent_loop(question: str, config: dict, max_calls: int = 10):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]
    
    tool_calls_log = []
    
    for _ in range(max_calls):
        # Call LLM with tools
        response = call_llm_with_tools(messages, config, TOOLS)
        
        # Check for tool calls
        if response has tool_calls:
            for tool_call in tool_calls:
                result = execute_tool(tool_call.name, tool_call.args)
                tool_calls_log.append({
                    "tool": tool_call.name,
                    "args": tool_call.args,
                    "result": result
                })
                # Append tool result to messages
        else:
            # Final answer
            return response.message, tool_calls_log
    
    # Max calls reached
    return current_answer, tool_calls_log
```

### Path Security

```python
def is_safe_path(path: str) -> bool:
    """Check if path is safe (no directory traversal)"""
    # Block ..
    if ".." in path:
        return False
    # Must be relative (no leading /)
    if path.startswith("/"):
        return False
    return True

def resolve_path(path: str) -> Path:
    """Resolve path and verify it's within project root"""
    project_root = Path(__file__).parent
    full_path = (project_root / path).resolve()
    
    # Verify path is within project root
    if not str(full_path).startswith(str(project_root.resolve())):
        raise ValueError(f"Path traversal detected: {path}")
    
    return full_path
```

---

## Testing Strategy

### Test 1: Merge Conflict Question

**Question:** "How do you resolve a merge conflict?"

**Expected:**
- `tool_calls` contains `read_file` with path `wiki/git-workflow.md` or similar
- `source` contains `wiki/git-workflow.md` with section anchor
- `answer` is non-empty and relevant

**Assertions:**
```python
assert any(tc["tool"] == "read_file" for tc in tool_calls)
assert "wiki/git" in source or "git" in source
assert len(answer) > 0
```

---

### Test 2: Wiki Files Question

**Question:** "What files are in the wiki?"

**Expected:**
- `tool_calls` contains `list_files` with path `wiki`
- `result` contains list of wiki files
- `answer` mentions some wiki files

**Assertions:**
```python
assert any(tc["tool"] == "list_files" for tc in tool_calls)
assert "wiki" in tc["args"]["path"] for the list_files call
assert len(answer) > 0
```

---

## Acceptance Criteria Checklist

- [ ] `plans/task-2.md` exists with implementation plan ✅
- [ ] `agent.py` defines `read_file` and `list_files` as tool schemas
- [ ] Agentic loop executes tool calls and feeds results back
- [ ] `tool_calls` in output is populated when tools are used
- [ ] `source` field correctly identifies wiki section
- [ ] Tools do not access files outside project directory
- [ ] `AGENT.md` documents tools and agentic loop
- [ ] 2 tool-calling regression tests exist and pass
- [ ] Git workflow: issue, branch, PR, approval, merge

---

## Timeline

| Step | Task | Estimated Time |
|------|------|----------------|
| 1 | Create this plan | 15 min |
| 2 | Implement read_file and list_files tools | 20 min |
| 3 | Implement agentic loop | 30 min |
| 4 | Update AGENT.md | 15 min |
| 5 | Write 2 regression tests | 20 min |
| 6 | Git workflow | 10 min |
| **Total** | | **~110 min** |
