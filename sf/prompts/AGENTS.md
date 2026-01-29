# sf/prompts/ — Gemini Prompt Templates

Static `.md` files loaded by `BestPractices.load()` in `pa_memory.py` as Tier 1 context. Injected into Gemini API calls for PA reasoning.

## Files

| File | Required | Content |
|------|----------|---------|
| `pa_system_prompt.md` | **yes** | PA system prompt — defines supervisor role, reasoning format, available functions |
| `coding_standards.md` | no | Code style rules passed to Gemini for task planning |
| `python_best_practices.md` | no | Python-specific conventions |
| `review_checklist.md` | no | Code review criteria |
| `security_rules.md` | no | Security rules (OWASP, input validation) |
| `qa_patterns.md` | no | QA and testing patterns |

## Loading

```python
# pa_memory.py
self.prompts_dir = Path(prompts_dir) or module_dir / "prompts"
self.best_practices = BestPractices.load(self.prompts_dir)
```

These are **not** SOP CLAUDE.md files (those are materialized per-workstation by `SOP.materialize()`). These are Gemini-side context for PA reasoning.
