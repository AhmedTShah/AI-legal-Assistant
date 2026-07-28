"""
state.py — LegalMind LangGraph Pipeline Shared State
=====================================================
Single shared state object passed between all LangGraph nodes.
Each node reads from state and returns only its updated fields.
"""

from __future__ import annotations
from typing import TypedDict, Optional, List, Annotated
import operator


class LegalMindState(TypedDict):

    # INPUT — filled at pipeline start
    user_query:              str

    # INTENT ROUTER NODE — fills these
    intent:                  Optional[str]        # "INTERNAL" or "EXTERNAL"
    intent_reason:           Optional[str]        # Why INTERNAL or EXTERNAL
