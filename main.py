"""
main.py — CLI entry point for the deep research agent.

Usage:
  python main.py
  python main.py "What are the biggest risks of AI in 2025?"
  python main.py "Explain quantum computing's current state" --no-stream
"""

import sys
import os
import uuid
import logging
import argparse
from dotenv import load_dotenv
from graph import build_graph
from state import create_initial_state

# ── Logging setup ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,     # Set to DEBUG to see everything
    format="%(levelname)s | %(name)s | %(message)s",
)

load_dotenv()


def validate_env():
    """Validate required environment variables before starting."""
    required = {"OPENAI_API_KEY": "https://platform.openai.com/api-keys"}
    optional = {
        "TAVILY_API_KEY": "https://tavily.com (free tier — better search quality)",
        "LANGCHAIN_API_KEY": "https://smith.langchain.com (free — enables tracing)",
    }

    missing_required = []
    for key, url in required.items():
        if not os.getenv(key):
            missing_required.append(f"  ❌ {key} — get it at: {url}")

    if missing_required:
        print("\n🚫 Missing required environment variables:")
        for msg in missing_required:
            print(msg)
        print("\nCopy .env.example to .env and fill in your keys.\n")
        sys.exit(1)

    # Warn about optional keys
    for key, url in optional.items():
        if not os.getenv(key):
            print(f"  ℹ️  {key} not set — optional but recommended. Get it: {url}")

    # Enable LangSmith tracing if key is present
    if os.getenv("LANGCHAIN_API_KEY"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ.setdefault("LANGCHAIN_PROJECT", "deep-research-agent")
        print("  🔭 LangSmith tracing: ENABLED")


def run_streaming(query: str):
    """Run the research graph with real-time streaming output."""
    print(f"\n{'═'*65}")
    print(f"  🧠 Deep Research Agent")
    print(f"  📌 Query: {query}")
    print(f"{'═'*65}")

    graph = build_graph(use_memory=True)
    initial_state = create_initial_state(query)
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n  🔑 Thread ID: {thread_id}")
    print(f"  (Save this to resume if interrupted)\n")

    # stream() yields one chunk per node completion
    for chunk in graph.stream(initial_state, config=config, stream_mode="updates"):
        # chunk = {"node_name": {partial_state_dict}}
        pass  # Nodes print their own progress — stream just drives the loop

    # Get final state
    final_state = graph.get_state(config)
    report = final_state.values.get("final_report", "")

    print(f"\n{'═'*65}")
    print("  📄 FINAL REPORT")
    print(f"{'═'*65}\n")
    print(report if report else "⚠️  No report generated.")
    print(f"\n{'═'*65}\n")

    return report


def run_simple(query: str):
    """Run without streaming — just invoke and wait."""
    print(f"\n🧠 Running deep research on: {query}\n")
    graph = build_graph(use_memory=False)
    final_state = graph.invoke(create_initial_state(query))
    report = final_state.get("final_report", "No report generated.")
    print("\n" + report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep Research AI Agent")
    parser.add_argument("query", nargs="*", help="Research query")
    parser.add_argument("--no-stream", action="store_true",
                        help="Disable streaming output")
    args = parser.parse_args()

    validate_env()

    query = " ".join(args.query) if args.query else (
        "What is the current state of AI agents in enterprise software, "
        "key players, limitations, and where the technology is headed in 2025?"
    )

    if args.no_stream:
        run_simple(query)
    else:
        run_streaming(query)
