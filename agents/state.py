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

    # QUERY DECOMPOSER NODE — fills these
    detected_language:       Optional[str]
    requires_urdu_translation: Optional[bool]
    primary_legal_issue:     Optional[str]
    jurisdiction:            Optional[str]
    key_parties:             Optional[List[str]]
    statutes_identified:     Optional[List[str]]
    sub_queries:             Optional[List[dict]] # List of SubQuery dicts/objects
    complexity_score:        Optional[int]

    # EXTERNAL WEB SEARCH NODE — fills these
    web_search_results:      Optional[List[dict]]

    # PIPELINE STATUS / INTERMEDIATE STATE
    status:                  Optional[str]
    retrieved_chunks:        Optional[List[dict]]
    verified_citations:      Optional[List[dict]]
    urdu_terms_found:        Optional[List[str]]

    # AGENT RESPONSES — filled by respective agents
    statute_agent_response:  Optional[str]

