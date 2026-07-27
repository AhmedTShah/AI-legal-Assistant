"""
agents/query_decomposer.py — Query Decomposer Agent for LegalMind Layer 3.
===========================================================================
Accepts a raw user legal query (English or Urdu) and uses Gemini to decompose
it into a set of focused, structured sub-queries with Qdrant-compatible filters.

Each sub-query is routed to a specialist agent:
    - case_law_agent   : Searches judgments in precedents_db (Qdrant)
    - statute_agent    : Searches statutory text in statutes_db (Qdrant)
    - timeline_agent   : Extracts chronology from user-uploaded case docs
    - jarah_prep_agent : Prepares cross-examination material

Usage:
    from agents.query_decomposer import QueryDecomposer

    decomposer = QueryDecomposer()
    result = decomposer.decompose("Can we get bail for my client arrested under PECA?")
    print(result.primary_legal_issue)
    for sq in result.sub_queries:
        print(sq.target_agent, sq.query_text, sq.qdrant_filters)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

from agents.schemas import DecomposedQuery
from config import CHAT_MODEL

load_dotenv()

logger = logging.getLogger(__name__)


# ── System Prompt ──────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """You are the Query Decomposer Agent for LegalMind — an AI-powered legal research assistant for Pakistani lawyers.

Your role is to analyze a user's legal query and decompose it into a structured JSON object that downstream specialist agents will use to search Qdrant vector databases.

## Pakistani Legal Context
- Courts: SCP (Supreme Court), IHC (Islamabad High Court), LHC (Lahore High Court), SHC (Sindh High Court), BHC (Balochistan High Court), PHC (Peshawar High Court)
- Common statutes: PPC (Pakistan Penal Code), CrPC (Code of Criminal Procedure), PECA 2016, FIA Act, NAB Ordinance, Constitution of Pakistan 1973, Civil Procedure Code, Contract Act
- Common case types: criminal, bail, cybercrime, defamation, civil, constitutional, family, corporate, tax, anti-corruption

## Qdrant Filter Fields Available
The precedents_db collection has these metadata fields you can filter on:
- court: ["SCP", "LHC", "IHC", "SHC", "BHC", "PHC"]
- year: integer (e.g. 2019, 2023)
- case_type: string (e.g. "criminal", "cybercrime", "civil", "bail")
- laws_cited: list of strings (statutes mentioned in the judgment)

## Specialist Agents
- case_law_agent: Searches Pakistani court judgment precedents. Use for questions about case outcomes, bail principles, judicial interpretation, sentencing patterns.
- statute_agent: Searches statutory text of Pakistani laws and acts. Use for questions about what a law says, definitions, punishments, procedures under specific sections.
- timeline_agent: Extracts chronological event sequences from user-uploaded case documents (FIRs, challan, statements). Use when the query involves reconstructing events.
- jarah_prep_agent: Prepares cross-examination material by comparing witness testimonies against official orders. Use when the query involves identifying contradictions or inconsistencies.

## Rules for Decomposition
1. Create between 1 and 5 sub-queries. Never more than 5.
2. Each sub-query must address a DISTINCT, non-overlapping aspect of the original query.
3. The query_text field in each sub-query must be a clean, keyword-rich search phrase (NOT the original verbose query). It will be embedded and used for vector similarity search.
4. Only add Qdrant filters when the query explicitly mentions a court, year range, statute, or case type. Never invent filters.
5. Assign complexity_score: 1 (single statute, single question) to 5 (multiple parties, multiple statutes, multiple courts).
6. If the query is in Urdu or a mix of Urdu/English, set requires_urdu_translation=true.

## Output Format
Return ONLY a valid JSON object matching this exact schema. No explanations, no markdown, no preamble.

{
  "original_query": "<verbatim user query>",
  "detected_language": "english" | "urdu" | "mixed",
  "requires_urdu_translation": true | false,
  "primary_legal_issue": "<1-2 sentence summary of core legal issue>",
  "jurisdiction": "<city/province or null>",
  "key_parties": ["<party name>", ...] or null,
  "statutes_identified": ["<Act Name Section X>", ...] or null,
  "complexity_score": 1-5,
  "sub_queries": [
    {
      "id": "SQ-1",
      "target_agent": "case_law_agent" | "statute_agent" | "timeline_agent" | "jarah_prep_agent",
      "query_text": "<focused search query for vector similarity>",
      "qdrant_filters": {
        "courts": ["SCP", "IHC", ...] or null,
        "year_from": <int> or null,
        "year_to": <int> or null,
        "case_type": "<string>" or null,
        "laws_cited": ["<statute>", ...] or null
      },
      "rationale": "<why this sub-query exists>"
    }
  ]
}"""


# ── Query Decomposer Agent ─────────────────────────────────────────────────────

class QueryDecomposer:
    """
    Decomposes a complex Pakistani legal query into structured sub-queries
    using Gemini as the reasoning backbone.

    Attributes:
        model_name (str): Gemini model to use for decomposition.
        max_retries (int): Number of retries on transient API failures.
    """

    def __init__(
        self,
        model_name: str = CHAT_MODEL,
        max_retries: int = 3,
    ):
        self.model_name  = model_name
        self.max_retries = max_retries
        self._configure_api()
        logger.info("QueryDecomposer initialized with model: %s", self.model_name)

    def _configure_api(self) -> None:
        """
        Configure the Gemini API key from environment.

        Strategy: Iterate through all keys in GEMINI_API_KEYS and pick the
        first one that is not blocked by a monthly spend cap. This is needed
        because Key #1 may have hit its monthly billing cap while Keys #2-4
        are still on the free daily quota and fully functional for chat.
        """
        # Gather all available keys
        raw_keys_str = os.getenv("GEMINI_API_KEYS", "")
        all_keys = [k.strip() for k in raw_keys_str.split(",") if k.strip()]

        # Also check single GEMINI_API_KEY as a fallback
        single_key = os.getenv("GEMINI_API_KEY", "").strip()
        if single_key and single_key not in all_keys:
            all_keys.insert(0, single_key)

        if not all_keys:
            raise EnvironmentError(
                "No Gemini API key found. Set GEMINI_API_KEY or GEMINI_API_KEYS in .env"
            )

        # Find first key that is NOT on monthly spend cap
        working_key = None
        for key in all_keys:
            genai.configure(api_key=key)
            try:
                # Quick probe: list models (very cheap, no quota cost)
                genai.embed_content(
                    model="models/gemini-embedding-001",
                    content="ping",
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=1,
                )
                working_key = key
                logger.info(
                    "QueryDecomposer using API key ending in ...%s", key[-6:]
                )
                break
            except Exception as exc:
                err = str(exc).lower()
                if "spend" in err or "monthly" in err:
                    logger.warning(
                        "Key ...%s has monthly spend cap — skipping.", key[-6:]
                    )
                    continue
                # Daily quota or other errors: still usable for chat model
                working_key = key
                logger.info(
                    "QueryDecomposer using API key ending in ...%s (quota note: %s)",
                    key[-6:], str(exc)[:60],
                )
                break

        if not working_key:
            raise EnvironmentError(
                "All Gemini API keys have exceeded their monthly spending caps. "
                "Please add a new key or reset the cap at https://ai.studio/spend"
            )

        genai.configure(api_key=working_key)
        self._active_key = working_key

    def _build_model(self) -> genai.GenerativeModel:
        """Instantiate the Gemini model with system prompt."""
        return genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=_SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=0.1,      # Low temperature for deterministic structured output
                max_output_tokens=2048,
                response_mime_type="application/json",  # Force JSON response mode
            ),
        )

    def _extract_json(self, raw_text: str) -> dict:
        """
        Extract and parse JSON from Gemini response.
        Handles cases where the model wraps JSON in markdown code blocks.
        """
        # Strip markdown code blocks if present
        cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("JSON parse error in Gemini response: %s\nRaw: %s", exc, raw_text[:500])
            raise ValueError(f"Gemini returned invalid JSON: {exc}") from exc

    def decompose(self, query: str) -> DecomposedQuery:
        """
        Decompose a raw user legal query into structured sub-queries.

        Args:
            query: The raw legal question from a lawyer or client.
                   Can be in English, Urdu, or a mix.

        Returns:
            DecomposedQuery: Fully validated Pydantic object with sub-queries
                             and Qdrant-compatible filters.

        Raises:
            ValueError: If Gemini returns unparseable output after all retries.
            RuntimeError: If all API attempts fail due to transient errors.
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty.")

        query = query.strip()
        logger.info("Decomposing query (%d chars): %s...", len(query), query[:80])

        model = self._build_model()
        prompt = f"Decompose the following Pakistani legal query:\n\n{query}"

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = model.generate_content(prompt)
                raw_text = response.text

                data = self._extract_json(raw_text)
                result = DecomposedQuery(**data)

                logger.info(
                    "Decomposition successful: %d sub-queries, complexity=%d",
                    len(result.sub_queries),
                    result.complexity_score,
                )
                return result

            except (ValueError, Exception) as exc:
                last_exc = exc
                logger.warning(
                    "Decomposition attempt %d/%d failed: %s",
                    attempt, self.max_retries, exc,
                )
                if attempt < self.max_retries:
                    time.sleep(2.0 * attempt)  # Exponential backoff

        raise RuntimeError(
            f"QueryDecomposer failed after {self.max_retries} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    def decompose_and_print(self, query: str) -> DecomposedQuery:
        """
        Decompose a query and print a human-readable summary to stdout.
        Useful for debugging and development.

        Args:
            query: The raw legal query string.

        Returns:
            DecomposedQuery object.
        """
        result = self.decompose(query)

        print("\n" + "=" * 70)
        print("QUERY DECOMPOSER — RESULTS")
        print("=" * 70)
        print(f"Original Query    : {result.original_query}")
        print(f"Language          : {result.detected_language.value}")
        print(f"Needs Translation : {result.requires_urdu_translation}")
        print(f"Jurisdiction      : {result.jurisdiction or 'Not specified'}")
        print(f"Primary Issue     : {result.primary_legal_issue}")
        print(f"Statutes Found    : {', '.join(result.statutes_identified) if result.statutes_identified else 'None'}")
        print(f"Complexity Score  : {result.complexity_score}/5")
        print(f"\nSub-Queries ({len(result.sub_queries)}):")
        for sq in result.sub_queries:
            print(f"\n  [{sq.id}] -> {sq.target_agent.value}")
            print(f"  Query   : {sq.query_text}")
            filters = sq.qdrant_filters
            if any([filters.courts, filters.year_from, filters.year_to, filters.case_type, filters.laws_cited]):
                print(f"  Filters : courts={filters.courts}, years={filters.year_from}-{filters.year_to}, "
                      f"case_type={filters.case_type}, laws={filters.laws_cited}")
            print(f"  Why     : {sq.rationale}")
        print("=" * 70 + "\n")

        return result
