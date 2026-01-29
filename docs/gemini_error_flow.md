# Gemini Error Handling Flow

## Before Fix (Broken Behavior)

```
┌─────────────────────────────────────────────────────────────────┐
│ Iteration N                                                     │
├─────────────────────────────────────────────────────────────────┤
│ 1. Claude executes task: "Add authentication to login page"    │
│ 2. PA calls Gemini for reasoning                               │
│ 3. Gemini returns error (network timeout)                      │
│ 4. PA creates NO_OP function result                            │
│ 5. _synthesize_instruction() returns:                          │
│    "[PA Note] Verification temporarily unavailable.            │
│     Please continue working on your current task."             │
│ 6. Claude receives vague message with NO CONTEXT               │
│ 7. Claude: "I don't have a current task. What should I do?"   │
└─────────────────────────────────────────────────────────────────┘
              ❌ CONTEXT LOST - ROGUE BEHAVIOR
```

## After Fix (Correct Behavior)

### Error #1-2: Preserve Context

```
┌─────────────────────────────────────────────────────────────────┐
│ Iteration N                                                     │
├─────────────────────────────────────────────────────────────────┤
│ current_instruction = "Add authentication to login page"       │
│ _last_valid_instruction = "Add authentication to login page"   │
│                                                                 │
│ 1. Claude executes instruction ✅                              │
│ 2. PA calls Gemini for reasoning                               │
│ 3. Gemini returns error (network timeout)                      │
│ 4. PA creates NO_OP function result                            │
│ 5. _synthesize_instruction() returns: ""  (empty string)       │
│ 6. Main loop sees empty string → keeps current instruction     │
│ 7. current_instruction = _last_valid_instruction               │
│                         = "Add authentication to login page"   │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Iteration N+1                                                   │
├─────────────────────────────────────────────────────────────────┤
│ 1. Claude receives SAME instruction: "Add authentication..."   │
│ 2. Claude continues working with FULL CONTEXT ✅               │
│ 3. Work proceeds normally                                      │
└─────────────────────────────────────────────────────────────────┘
              ✅ CONTEXT PRESERVED - FOCUSED WORK
```

### Error #3: Save Session

```
┌─────────────────────────────────────────────────────────────────┐
│ Iteration N+2 (Third consecutive error)                        │
├─────────────────────────────────────────────────────────────────┤
│ 1. Claude executes instruction                                 │
│ 2. PA calls Gemini for reasoning                               │
│ 3. Gemini returns error (still failing)                        │
│ 4. _consecutive_errors = 3                                     │
│ 5. PA creates SAVE_SESSION function call                       │
│ 6. Session saved with:                                         │
│    - session_id                                                │
│    - current task                                              │
│    - work progress                                             │
│    - file changes                                              │
│ 7. User sees: "[PA] Session saved. Resume with session_id:..." │
│ 8. Loop exits gracefully                                       │
└─────────────────────────────────────────────────────────────────┘
              ✅ GRACEFUL EXIT - RESUMABLE STATE
```

### Successful Recovery

```
┌─────────────────────────────────────────────────────────────────┐
│ Iteration N (After 1-2 errors)                                 │
├─────────────────────────────────────────────────────────────────┤
│ 1. Claude executes instruction (preserved context)             │
│ 2. PA calls Gemini for reasoning                               │
│ 3. Gemini responds successfully ✅                             │
│ 4. PA parses JSON response                                     │
│ 5. _consecutive_errors = 0  (RESET)                            │
│ 6. Normal reasoning resumes                                    │
│ 7. Fresh instruction synthesized based on progress             │
└─────────────────────────────────────────────────────────────────┘
              ✅ RECOVERED - NORMAL OPERATION
```

## Key Code Changes

### pa.py - State Tracking
```python
# Track instruction context
self._original_task: str = ""
self._last_valid_instruction: str = ""

# Initialize on task start
self._original_task = task
self._last_valid_instruction = task

# Update on new instructions
if synthesized:
    current_instruction = synthesized
    self._last_valid_instruction = synthesized
else:
    # Preserve during errors
    current_instruction = self._last_valid_instruction
```

### pa.py - NO_OP Handling
```python
def _synthesize_instruction(self, result: FunctionResult) -> str:
    # ...
    elif result.name == FunctionName.NO_OP:
        # Empty string = keep current instruction
        return ""
```

### pa_agent.py - Error Output
```python
def _error_output(self, error_info: dict) -> AgentLoopOutput:
    self._consecutive_errors += 1

    if self._consecutive_errors >= 3:
        # Trigger session save
        return AgentLoopOutput(
            # ... with SAVE_SESSION function
        )

    # Otherwise NO_OP (preserves instruction in main loop)
    return AgentLoopOutput(
        # ... with NO_OP function
    )
```

## Error Counter Behavior

```
Iteration  | Gemini Status | Error Count | Action        | Instruction
-----------|---------------|-------------|---------------|------------------
1          | Success       | 0           | Normal        | "Task A"
2          | Error         | 1 → NO_OP   | Preserve      | "Task A" (same)
3          | Error         | 2 → NO_OP   | Preserve      | "Task A" (same)
4          | Success       | 0 (reset)   | Normal        | "Task B" (new)
5          | Error         | 1 → NO_OP   | Preserve      | "Task B" (same)
6          | Error         | 2 → NO_OP   | Preserve      | "Task B" (same)
7          | Error         | 3 → SAVE    | Exit          | N/A
```

## Benefits

1. **Context Preservation**: Claude never loses track of what it's working on
2. **Graceful Degradation**: System continues functioning during API outages
3. **Automatic Recovery**: Error counter resets on successful Gemini response
4. **Session Resumability**: After 3 errors, state is saved for later resumption
5. **Clear Communication**: Users know what's happening and how to recover
