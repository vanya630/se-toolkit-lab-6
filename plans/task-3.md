# Task 3 Plan: The System Agent

## Overview

Extend the Task 2 agent with a **query_api** tool that can call the deployed backend API. This enables the agent to answer:
1. **Static system facts** — framework, ports, status codes (from source code)
2. **Data-dependent queries** — item count, scores, analytics (from live API)

## Architecture Changes

### New Tool: query_api

**Purpose:** Send HTTP requests to the deployed backend API.

**Schema:**
```json
{
  "name": "query_api",
  "description": "Query the deployed backend API. Use this to get live data from the system.",
  "parameters": {
    "type": "object",
    "properties": {
      "method": {
        "type": "string",
        "description": "HTTP method (GET, POST, PUT, DELETE)",
        "enum": ["GET", "POST", "PUT", "DELETE"]
      },
      "path": {
        "type": "string",
        "description": "API endpoint path (e.g., '/items/', '/analytics/completion-rate')"
      },
      "body": {
        "type": "string",
        "description": "Optional JSON request body (for POST/PUT)"
      }
    },
    "required": ["method", "path"]
  }
}
```

**Implementation:**
```python
def query_api(method: str, path: str, body: str = None) -> str:
    # Read LMS_API_KEY from environment
    # Build URL from AGENT_API_BASE_URL
    # Send HTTP request with Authorization: Bearer <LMS_API_KEY>
    # Return JSON response with status_code and body
```

---

## Environment Variables

The agent must read ALL configuration from environment variables:

| Variable | Purpose | Source | Required |
|----------|---------|--------|----------|
| `LLM_API_KEY` | LLM provider API key | `.env.agent.secret` | ✅ |
| `LLM_API_BASE` | LLM API endpoint URL | `.env.agent.secret` | ✅ |
| `LLM_MODEL` | Model name | `.env.agent.secret` | ✅ |
| `LMS_API_KEY` | Backend API key for query_api auth | `.env.docker.secret` | ✅ |
| `AGENT_API_BASE_URL` | Base URL for query_api | Optional, defaults to `http://localhost:42002` | ❌ |

### Loading Strategy

```python
def load_config() -> dict:
    # Load from .env files for local development
    load_dotenv(".env.agent.secret")
    load_dotenv(".env.docker.secret")
    
    # Read from environment variables (autochecker injects these)
    config = {
        "llm_api_key": os.getenv("LLM_API_KEY"),
        "llm_api_base": os.getenv("LLM_API_BASE"),
        "llm_model": os.getenv("LLM_MODEL"),
        "lms_api_key": os.getenv("LMS_API_KEY"),
        "agent_api_base_url": os.getenv("AGENT_API_BASE_URL", "http://localhost:42002"),
    }
    
    # Validate required fields
    if not config["llm_api_key"]:
        raise SystemExit("LLM_API_KEY not found")
    # ... etc
    
    return config
```

### Important: Two Distinct Keys

| Key | Purpose | File |
|-----|---------|------|
| `LLM_API_KEY` | Authenticates with LLM provider (Qwen, OpenAI, etc.) | `.env.agent.secret` |
| `LMS_API_KEY` | Authenticates with backend API (`Authorization: Bearer`) | `.env.docker.secret` |

**Never mix these up!**

---

## System Prompt Update

The system prompt must guide the LLM to choose the right tool:

### Updated System Prompt

```
You are a system agent that answers questions about the project using multiple sources.

You have access to three types of tools:

1. **Wiki tools** (list_files, read_file):
   - Use these to read documentation in the wiki/ directory
   - Good for: workflow questions, how-to guides, policies

2. **Source code tool** (read_file):
   - Use this to read source code files (.py, .yml, .md, etc.)
   - Good for: framework identification, code structure, bug diagnosis

3. **API tool** (query_api):
   - Use this to query the live backend API
   - Good for: current data counts, status codes, analytics, error messages
   - Always use for questions about "how many", "what is the current", "query"

To answer a question:
1. Identify what type of information is needed:
   - Documentation? → Use list_files + read_file on wiki/
   - Source code? → Use read_file on backend/, docker-compose.yml, etc.
   - Live data? → Use query_api with appropriate endpoint
2. Use the appropriate tool(s)
3. Provide a concise answer with source reference

Rules:
- For data questions (counts, statistics), ALWAYS use query_api first
- For code questions (framework, structure), read the source files
- For workflow questions, check the wiki documentation
- Include source references when possible
- If you get an API error, read the source code to diagnose the bug
```

### Tool Selection Strategy

| Question Type | Example | Tools to Use |
|---------------|---------|--------------|
| Wiki lookup | "How to protect a branch?" | `list_files("wiki")` → `read_file("wiki/github.md")` |
| System fact | "What framework?" | `read_file("backend/app/main.py")` |
| Data query | "How many items?" | `query_api("GET", "/items/")` |
| Status code | "What status without auth?" | `query_api("GET", "/items/", headers={})` |
| Bug diagnosis | "Why does /analytics crash?" | `query_api()` → `read_file("backend/app/routers/analytics.py")` |

---

## Implementation Details

### query_api Implementation

```python
def query_api(method: str, path: str, body: str = None) -> str:
    """
    Query the backend API with authentication.
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE)
        path: API endpoint path
        body: Optional JSON request body
    
    Returns:
        JSON string with status_code and response body
    """
    import httpx
    
    # Read config from environment
    api_base = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")
    lms_api_key = os.getenv("LMS_API_KEY")
    
    if not lms_api_key:
        return json.dumps({"error": "LMS_API_KEY not configured"})
    
    url = f"{api_base}{path}"
    
    headers = {
        "Authorization": f"Bearer {lms_api_key}",
        "Content-Type": "application/json",
    }
    
    try:
        with httpx.Client(timeout=30) as client:
            if method == "GET":
                response = client.get(url, headers=headers)
            elif method == "POST":
                response = client.post(url, headers=headers, json=json.loads(body) if body else {})
            # ... handle other methods
            
            return json.dumps({
                "status_code": response.status_code,
                "body": response.text,
            })
            
    except Exception as e:
        return json.dumps({"error": str(e)})
```

### Authentication Flow

```
┌─────────────────────────────────────────────────────────────┐
│  query_api() call                                           │
│  - method: "GET"                                            │
│  - path: "/items/"                                          │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Read LMS_API_KEY from environment                          │
│  - os.getenv("LMS_API_KEY")                                 │
│  - From .env.docker.secret (local) or autochecker injection │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Build HTTP request                                         │
│  - URL: http://localhost:42002/items/                       │
│  - Headers: Authorization: Bearer <LMS_API_KEY>             │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Backend validates API key                                  │
│  - If valid: return data                                    │
│  - If invalid: return 401 Unauthorized                      │
└─────────────────────────────────────────────────────────────┘
```

---

## Benchmark Questions

The 10 local evaluation questions:

| # | Question | Type | Expected Tools | Expected Answer |
|---|----------|------|----------------|-----------------|
| 0 | Wiki: protect branch steps | Wiki lookup | `read_file` | branch, protect |
| 1 | Wiki: SSH to VM | Wiki lookup | `read_file` | ssh, key, connect |
| 2 | What Python web framework? | Source code | `read_file` | FastAPI |
| 3 | List API router modules | Source code | `list_files` | items, interactions, analytics, pipeline |
| 4 | How many items in database? | Data query | `query_api` | number > 0 |
| 5 | Status code without auth? | Data query | `query_api` | 401 or 403 |
| 6 | /analytics/completion-rate error | Bug diagnosis | `query_api`, `read_file` | ZeroDivisionError |
| 7 | /analytics/top-learners crash | Bug diagnosis | `query_api`, `read_file` | TypeError, None, sorted |
| 8 | Request journey (Caddy → DB) | Reasoning | `read_file` | ≥4 hops |
| 9 | ETL idempotency | Reasoning | `read_file` | external_id check |

---

## Testing Strategy

### Test 1: Framework Question

**Question:** "What framework does the backend use?"

**Expected:**
- Uses `read_file` to read backend source code
- Answer contains "FastAPI"
- Source references a Python file

**Assertions:**
```python
assert any(tc["tool"] == "read_file" for tc in tool_calls)
assert "fastapi" in response["answer"].lower()
```

---

### Test 2: Database Count Question

**Question:** "How many items are in the database?"

**Expected:**
- Uses `query_api` with GET /items/
- Answer contains a number
- tool_calls contains API response

**Assertions:**
```python
assert any(tc["tool"] == "query_api" for tc in tool_calls)
assert any("/items/" in str(tc.get("args", {})) for tc in tool_calls if tc["tool"] == "query_api")
```

---

## Iteration Strategy

### Step 1: Initial Run

```bash
uv run run_eval.py
```

Expect some failures initially.

### Step 2: Analyze Failures

For each failure:
1. **Wrong tool?** → Improve system prompt tool selection guidance
2. **Tool error?** → Fix tool implementation
3. **Wrong arguments?** → Clarify tool schema descriptions
4. **Timeout?** → Reduce max iterations or optimize tool calls

### Step 3: Fix and Re-run

```bash
# Fix the issue in agent.py
# Then re-run
uv run run_eval.py
```

### Step 4: Document Lessons Learned

After all tests pass, update AGENT.md with:
- What failed initially
- How you fixed it
- Final score

---

## Acceptance Criteria Checklist

- [ ] `plans/task-3.md` exists with implementation plan ✅
- [ ] `agent.py` defines `query_api` as function-calling schema
- [ ] `query_api` authenticates with `LMS_API_KEY` from environment
- [ ] Agent reads all LLM config from environment variables
- [ ] Agent reads `AGENT_API_BASE_URL` from environment (defaults to localhost)
- [ ] Answers static system questions correctly
- [ ] Answers data-dependent questions correctly
- [ ] `run_eval.py` passes all 10 local questions
- [ ] `AGENT.md` documents final architecture (≥200 words)
- [ ] 2 tool-calling regression tests exist and pass
- [ ] Autochecker bot benchmark passes
- [ ] Git workflow: issue, branch, PR, approval, merge

---

## Timeline

| Step | Task | Estimated Time |
|------|------|----------------|
| 1 | Create this plan | 15 min |
| 2 | Implement query_api tool | 20 min |
| 3 | Update system prompt | 15 min |
| 4 | Run eval, iterate on failures | 60 min |
| 5 | Update AGENT.md | 20 min |
| 6 | Write 2 regression tests | 20 min |
| 7 | Git workflow | 10 min |
| **Total** | | **~160 min** |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| API authentication fails | Verify LMS_API_KEY matches .env.docker.secret |
| Agent times out | Reduce max tool calls, use faster LLM |
| Wrong tool selected | Improve system prompt with clearer examples |
| API returns error | Handle errors gracefully, return error message to LLM |
| LLM ignores tools | Use tool_choice="auto" or adjust temperature |
