"""Compatibility import surface for need-driven retrieval planning.

Requirements now live in StructuredGoal and missing information lives only in
InformationNeed. No coverage or gap object is persisted.
"""
from policypilot.retrieval import build_retrieval_call, build_retrieval_query

__all__ = ["build_retrieval_call", "build_retrieval_query"]
