"""
agents/schemas.py — Pydantic schemas for Query Decomposer Agent output.
========================================================================
These schemas define the structured data contracts between:
    - QueryDecomposer Agent (producer)
    - Case Law Agent, Statute Agent, Timeline Agent, Jarah Prep Agent (consumers)

All Qdrant filter fields mirror the metadata stored in `precedents_db`:
    court, year, case_type, laws_cited  (see pipeline/ingest_precedents.py)
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class TargetAgent(str, Enum):
    """Downstream specialist agents that can handle a sub-query."""
    CASE_LAW   = "case_law_agent"    # Searches judgments in precedents_db
    STATUTE    = "statute_agent"     # Searches acts/codes in statutes_db
    TIMELINE   = "timeline_agent"    # Extracts chronology from case documents
    JARAH_PREP = "jarah_prep_agent"  # Compares testimonies/orders for cross-exam


class Language(str, Enum):
    """Language detected in the original user query."""
    ENGLISH = "english"
    URDU    = "urdu"
    MIXED   = "mixed"


class PakistaniCourt(str, Enum):
    """Pakistani courts tracked in Qdrant precedents_db."""
    SCP  = "SCP"   # Supreme Court of Pakistan
    LHC  = "LHC"   # Lahore High Court
    IHC  = "IHC"   # Islamabad High Court
    SHC  = "SHC"   # Sindh High Court
    BHC  = "BHC"   # Balochistan High Court
    PHC  = "PHC"   # Peshawar High Court
    AHC  = "AHC"   # Azad Kashmir High Court


# ── Sub-Query Schema ───────────────────────────────────────────────────────────

class QdrantFilters(BaseModel):
    """
    Metadata filters that map directly to Qdrant `precedents_db` payload fields.
    Any field set to None means no filter is applied for that dimension.
    """
    courts: Optional[List[PakistaniCourt]] = Field(
        default=None,
        description="Specific courts to restrict search to (e.g. ['IHC', 'SCP'])."
    )
    year_from: Optional[int] = Field(
        default=None,
        description="Start year for temporal filtering (inclusive)."
    )
    year_to: Optional[int] = Field(
        default=None,
        description="End year for temporal filtering (inclusive)."
    )
    case_type: Optional[str] = Field(
        default=None,
        description="Legal domain (e.g. 'cybercrime', 'criminal', 'bail', 'civil')."
    )
    laws_cited: Optional[List[str]] = Field(
        default=None,
        description="Specific statutes or sections that must appear in cited laws."
    )


class SubQuery(BaseModel):
    """
    A single focused sub-query derived from decomposing the original user query.
    Each sub-query is self-contained and routable to exactly one specialist agent.
    """
    id: str = Field(
        description="Unique identifier for this sub-query (e.g. 'SQ-1', 'SQ-2')."
    )
    target_agent: TargetAgent = Field(
        description="Which specialist agent should handle this sub-query."
    )
    query_text: str = Field(
        description=(
            "A clean, focused, search-optimized query string for this sub-task. "
            "Should be concise, using relevant legal keywords. "
            "This string will be embedded and used for Qdrant vector similarity search."
        )
    )
    qdrant_filters: QdrantFilters = Field(
        default_factory=QdrantFilters,
        description="Structured Qdrant metadata filters for this sub-query."
    )
    rationale: str = Field(
        description="Brief explanation of why this sub-query was created and what it answers."
    )


# ── Top-Level Decomposed Query Schema ─────────────────────────────────────────

class DecomposedQuery(BaseModel):
    """
    The full structured output of the Query Decomposer Agent.
    Contains all context extracted from the original user legal query,
    plus an ordered list of actionable sub-queries for downstream agents.
    """
    original_query: str = Field(
        description="The original, verbatim query as submitted by the user."
    )
    detected_language: Language = Field(
        description="Language detected in the original query."
    )
    requires_urdu_translation: bool = Field(
        description=(
            "True if the query or its answer must pass through the "
            "Bilingual Urdu Translator agent before downstream processing."
        )
    )
    primary_legal_issue: str = Field(
        description=(
            "A concise 1-2 sentence summary of the core legal issue raised "
            "in the query (in English, even if original was Urdu)."
        )
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        description="Geographic jurisdiction mentioned in the query (e.g. 'Islamabad', 'Karachi', 'Punjab')."
    )
    key_parties: Optional[List[str]] = Field(
        default=None,
        description="Names of individuals, organizations, or entities identified in the query."
    )
    statutes_identified: Optional[List[str]] = Field(
        default=None,
        description="Specific Pakistani statutes, sections, or ordinances explicitly mentioned."
    )
    sub_queries: List[SubQuery] = Field(
        description=(
            "Ordered list of focused sub-queries to dispatch to specialist agents. "
            "Each sub-query should address a distinct aspect of the original legal question."
        )
    )
    complexity_score: int = Field(
        ge=1,
        le=5,
        description=(
            "Estimated complexity of the query on a 1-5 scale: "
            "1=simple single-issue, 5=complex multi-statute multi-party case."
        )
    )
