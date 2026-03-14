from state import ResearchState

def planner_node(state: ResearchState) -> dict:
    # Importing from planner.py
    from planner import planner_node as _planner_node
    return _planner_node(state)

def searcher_node(state: ResearchState) -> dict:
    from searcher import searcher_node as _searcher_node
    return _searcher_node(state)

def reflector_node(state: ResearchState) -> dict:
    from reflector import reflector_node as _reflector_node
    return _reflector_node(state)

def writer_node(state: ResearchState) -> dict:
    from writer import writer_node as _writer_node
    return _writer_node(state)

def critic_node(state: ResearchState) -> dict:
    from critic import critic_node as _critic_node
    return _critic_node(state)
