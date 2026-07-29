"""
agents/ — LegalMind Layer 3 Agentic Reasoning Components
==========================================================
Each agent has a single, focused responsibility in the legal research pipeline.

Agents:
    - QueryDecomposer : Breaks a complex user legal query into focused sub-queries
                        with Qdrant-compatible metadata filters.
    - CaseLawAgent    : Retrieves relevant precedent chunks from Qdrant based on sub-queries.
    - SynthesisAgent  : Synthesizes final legal memos from retrieved precedents.
"""

from .query_decomposer import QueryDecomposer
from .case_law_agent import CaseLawAgent
from .synthesis_agent import SynthesisAgent

__all__ = ["QueryDecomposer", "CaseLawAgent", "SynthesisAgent"]
