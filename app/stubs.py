"""Placeholder specialists until tickets 05 (Knowledge) and 06 (Support) land.

Both follow the graph's specialist interface: `(GraphState) -> {answer, sources, steps, tokens}`.
"""

from app.graph import GraphState


def stub_knowledge(state: GraphState) -> dict:
    return {
        "answer": "The Knowledge Agent is not available yet.",
        "sources": [],
        "steps": ["knowledge"],
        "tokens": 0,
    }


def stub_support(state: GraphState) -> dict:
    return {
        "answer": "The Customer Support Agent is not available yet.",
        "sources": [],
        "steps": ["support"],
        "tokens": 0,
    }
