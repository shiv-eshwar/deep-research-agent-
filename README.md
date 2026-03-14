# 🧠 Deep Research Agent

A **production-grade deep research AI agent** built with LangGraph and OpenAI.

It searches the web, evaluates sources, reflects on gaps, and writes comprehensive cited reports — autonomously.

---

## How It Works

```
Query → Planner → Searcher → Reflector → Writer → Critic → Report
                     ↑            |                   ↑       |
                     └── loop ────┘                   └─ loop ┘
                    (if gaps found)               (if needs revision)
```

| Node | Model | Job |
|------|-------|-----|
| **Planner** | gpt-4o-mini | Breaks query into 5-7 targeted sub-questions |
| **Searcher** | gpt-4o-mini | Searches web, scrapes sources, builds knowledge base |
| **Reflector** | gpt-4o-mini | Scores coverage (0–1), identifies gaps, decides to loop or write |
| **Writer** | gpt-4o | Writes a 1000–1500 word cited Markdown report |
| **Critic** | gpt-4o-mini | Scores quality (0–1), approves or sends back for revision |

---

## Project Structure

```
deep_research_agent/
├── state.py                      ← State schema + Pydantic models
├── prompts.py                    ← All LLM prompts (tune here)
├── tools.py                      ← Web search + scraper
├── nodes/
│   ├── planner.py                ← Sub-question decomposition
│   ├── searcher.py               ← Web search + knowledge synthesis
│   ├── reflector.py              ← Coverage evaluation + gap detection
│   ├── writer.py                 ← Report writing + revision
│   └── critic.py                 ← Quality scoring + approval
├── graph.py                      ← StateGraph with routing logic
├── main.py                       ← CLI entry point
├── api.py                        ← FastAPI (sync, streaming, async)
├── Dockerfile                    ← Multi-stage production build
├── .github/workflows/deploy.yml  ← CI/CD: push → GCP auto-deploy
└── requirements.txt
```

---

## Setup

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/deep-research-agent.git
cd deep-research-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get API Keys

| Key | Required | Get It | Cost |
|-----|----------|--------|------|
| `OPENAI_API_KEY` | ✅ | [platform.openai.com](https://platform.openai.com/api-keys) | ~$0.10-0.30/run |
| `TAVILY_API_KEY` | Recommended | [tavily.com](https://tavily.com) | Free (1000/month) |
| `LANGCHAIN_API_KEY` | Optional | [smith.langchain.com](https://smith.langchain.com) | Free tier |

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your keys
```

### 4. Run

```bash
# Default query
python main.py

# Custom query
python main.py "What are the risks and opportunities of autonomous AI agents in 2025?"

# No streaming
python main.py "your query" --no-stream

# Visualize the graph structure
python graph.py
```

---

## Run as API

```bash
uvicorn api:app --reload --port 8080
```

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Liveness check |
| `/ready` | GET | Readiness check (checks API keys) |
| `/research` | POST | Sync — waits for full result |
| `/research/stream` | POST | SSE streaming — real-time node updates |
| `/research/async` | POST | Background job — returns job_id |
| `/research/jobs/{id}` | GET | Poll job status |
| `/docs` | GET | Auto-generated API docs |

### Example curl calls

```bash
# Sync research
curl -X POST http://localhost:8080/research \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the current state of AI agents in enterprise software?"}'

# Start async job
curl -X POST http://localhost:8080/research/async \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain the risks of AGI development"}'

# Check job status
curl http://localhost:8080/research/jobs/YOUR_JOB_ID
```

---

## Docker

```bash
# Build image
docker build -t deep-research-agent .

# Run container
docker run -p 8080:8080 --env-file .env deep-research-agent

# Test it
curl http://localhost:8080/health
```

---

## Deploy to Google Cloud Run

### One-Time Setup

```bash
# Install: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud projects create deep-research-agent-001
gcloud config set project deep-research-agent-001

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com
```

### Manual Deploy

```bash
# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/deep-research-agent

# Deploy
gcloud run deploy deep-research-agent \
  --image gcr.io/YOUR_PROJECT_ID/deep-research-agent \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout 540 \
  --set-env-vars "OPENAI_API_KEY=sk-...,TAVILY_API_KEY=tvly-..."
```

### Automated Deploy (GitHub Actions)

Every `git push main` automatically deploys. Add these GitHub Secrets:

```
GCP_SA_KEY      → Your GCP service account JSON key
GCP_PROJECT_ID  → Your GCP project ID
OPENAI_API_KEY  → Your OpenAI key
TAVILY_API_KEY  → Your Tavily key
```

---

## Tuning the Agent

| What to change | Where |
|---------------|-------|
| System prompts for each agent | `prompts.py` |
| Max search loops | `state.py` → `MAX_RESEARCH_ITERATIONS` |
| Max revision loops | `state.py` → `MAX_REVISIONS` |
| Minimum coverage to write | `state.py` → `MIN_COVERAGE_TO_WRITE` |
| LLM model per node | `nodes/*.py` → `ChatOpenAI(model=...)` |
| Number of search results | `nodes/searcher.py` → `search_web(max_results=...)` |

---

## Learning Exercises

| Exercise | What You Learn |
|----------|---------------|
| Add a `fact_checker` node between writer and critic | Node insertion into existing graph |
| Run planner and first search in parallel | LangGraph `Send` API |
| Swap `MemorySaver` for `SqliteSaver` | Persistent checkpointing |
| Enable LangSmith and trace a full run | Production observability |
| Add `interrupt_before=["critic"]` | Human-in-the-loop pattern |
| Replace OpenAI with Claude | LLM provider swap |
| Add streaming to a simple React frontend | Full-stack AI app |
