# Gemini Error Handling Fix

## Problem Description

When PA encounters a Gemini API error, the agent would "go rogue" by sending vague instructions to Claude like "Continue with the task" without any context. This led to unfocused and often incorrect results because Claude had no memory of what it was supposed to be working on.

### Root Cause Analysis

The issue occurred in the following flow:

1. **Gemini API Error** → `gemini_client.py:140-149` returns `[GEMINI_ERROR:...]` after retries
2. **Error Detection** → `pa_agent.py:471-473` detects error string and calls `_error_output()`
3. **NO_OP Function** → `pa_agent.py:551-595` creates a NO_OP function call with error metadata
4. **Vague Instruction** → `pa.py:397-407` in `_synthesize_instruction()` returned:
   ```python
   "[PA Note] Verification temporarily unavailable ({error_type}). Please continue working on your current task."
   ```
5. **Context Loss** → Claude receives this message with no context about what "your current task" is

## Solution Implemented

### 1. Instruction Context Preservation (`pa.py`)

**Added state tracking** (pa.py:65-67):
```python
# Track the original task and last valid instruction for error recovery
self._original_task: str = ""
self._last_valid_instruction: str = ""
```

**Initialize on task start** (pa.py:98-100):
```python
# Store original task for error recovery
self._original_task = task
self._last_valid_instruction = task
```

**Update instruction tracking** (pa.py:178-192):
```python
# Get next instruction (prioritize queued, then synthesized)
next_instruction = self.agent.get_claude_instruction()
if next_instruction:
    current_instruction = next_instruction
    self._last_valid_instruction = next_instruction
else:
    synthesized = self._synthesize_instruction(result)
    if synthesized:
        current_instruction = synthesized
        self._last_valid_instruction = synthesized
    else:
        # During error states (NO_OP), keep the last valid instruction
        # This ensures Claude maintains context even when PA can't reason
        current_instruction = self._last_valid_instruction
```

### 2. NO_OP Instruction Handling (`pa.py`)

**Simplified NO_OP handling** (pa.py:410-415):
```python
elif result.name == FunctionName.NO_OP:
    # For NO_OP, remain silent (empty string signals no instruction change)
    # This prevents sending confusing "Continue" messages during error states
    # The main loop will keep the previous instruction instead
    return ""
```

This change means:
- NO_OP now returns an empty string instead of a vague message
- The main loop interprets empty string as "keep current instruction"
- Claude continues with the last valid instruction, maintaining full context

### 3. Enhanced Error Messages (`pa_agent.py`)

**Updated error output** (pa_agent.py:551-595):
```python
def _error_output(self, error_info: dict) -> AgentLoopOutput:
    """Return output for Gemini API errors after retries exhausted."""
    # ... error counting logic ...

    # After 3 consecutive errors, request session save
    if self._consecutive_errors >= 3:
        session_id = self._memory.session.session_id

        return AgentLoopOutput(
            reasoning=PAReasoning(
                current_state=f"Gemini API failure: {error_type} (3+ consecutive errors)",
                claude_progress="Unable to verify - API unavailable",
                insights=f"Repeated Gemini errors: {message}. Saving session for resumption.",
                decision=f"Save session state and exit gracefully. Session ID: {session_id}",
            ),
            # ... SAVE_SESSION function call ...
        )
```

**Updated parse fallback** (pa_agent.py:597-611):
- Now increments error counter for parse failures
- Provides clearer messaging about preserving instruction context
- Maintains same NO_OP behavior to preserve instruction

### 4. Session Save Improvements (`pa.py`)

**Better exit messaging** (pa.py:171-176):
```python
if result.metadata.get("exit_gracefully"):
    # Save session with error context for resumption
    yield self._emit(
        f"[PA] Session saved due to errors. Resume with session_id: {self.session_id}",
        EventType.TEXT,
        source="pa"
    )
    break
```

## Key Behaviors After Fix

### During Single Gemini Error (Errors 1-2)
1. PA detects Gemini error and creates NO_OP
2. `_synthesize_instruction()` returns empty string
3. Main loop keeps `_last_valid_instruction`
4. Claude continues with the same focused instruction
5. User sees: `"[no_op] Gemini parse error (attempt 1/3) - preserving instruction context"`

### After 3 Consecutive Errors
1. PA creates SAVE_SESSION function call
2. Session state is saved with full context
3. User sees: `"[PA] Session saved due to errors. Resume with session_id: abc123"`
4. User can resume later with: `pa --session-id abc123`

### After Successful Gemini Response
1. Error counter resets to 0 (pa_agent.py:504)
2. Normal PA reasoning resumes
3. Fresh instructions are synthesized

## Testing Recommendations

To test these fixes:

1. **Simulate Gemini API errors** by temporarily modifying `gemini_client.py` to return error strings
2. **Verify instruction preservation** by checking Claude receives the same instruction during errors
3. **Test session save** by triggering 3 consecutive errors and confirming session is saved
4. **Test recovery** by resuming from a saved session ID

## Files Modified

- `agentproxy/pa.py` (50-67, 98-100, 171-192, 410-415)
- `agentproxy/pa_agent.py` (551-611)

## Impact

This fix ensures that:
- ✅ Claude never loses context during Gemini errors
- ✅ PA preserves the last valid instruction during error states
- ✅ After 3 errors, session is saved with resumability
- ✅ Clear messaging to users about error states and recovery
- ✅ No more "rogue" Claude behavior during API outages
