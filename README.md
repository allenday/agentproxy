# CCP - Code Custodian Persona

AI supervisor for Claude Code.

## Setup
```bash
pip install fastapi uvicorn pydantic
echo "GEMINI_API_KEY=your_key" > .env
```

## Mode 1: CLI
```bash
python cli.py "Create hello.py"
python cli.py -d ./myproject "Fix bug"
python cli.py --add-screenshot design.png "Match this UI"
```

## Mode 2: Server
```bash
python server.py --port 8080
```

```bash
# Start task
curl -N -X POST http://localhost:8080/task \
  -H "Content-Type: application/json" \
  -d '{"task": "Create hello.py", "working_dir": "./sandbox"}'

# With screenshot
curl -N -X POST http://localhost:8080/task \
  -H "Content-Type: application/json" \
  -d '{"task": "Match this UI", "screenshots": [{"path": "/path/to/design.png"}]}'

# Other endpoints
curl http://localhost:8080/health
curl http://localhost:8080/sessions
```

## Requirements
- Python 3.9+
- Claude CLI (`claude` command)
- Gemini API key
