"""
intent_router.py — LegalMind Intent Router Agent (Node 1)
==========================================================
Pattern:
    Step 1 — Define Pydantic Model for strict output validation.
    Step 2 — Invoke Gemini API using google.generativeai with native JSON response schema.
    Step 3 — Extract validated fields and return as TypedDict dict.

LangGraph Routing:
    route_by_intent() is the Conditional Edge function.
    Returns "external_offtopic" or "internal_pipeline" to direct the graph.
"""

import os
import sys
import json
from typing import Literal
from pydantic import BaseModel, Field

# UTF-8 stdout reconfigure for Windows Terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import google.generativeai as genai

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from config import CHAT_MODEL
from agents.state import LegalMindState


# ──────────────────────────────────────────────────────────────
# STEP 1: PYDANTIC MODEL
# Defines the strict shape Gemini must return.
# ──────────────────────────────────────────────────────────────

class IntentClassification(BaseModel):
    intent: Literal["INTERNAL", "EXTERNAL"] = Field(
        description="INTERNAL if the query is related to Pakistani law. EXTERNAL if the query is NOT related to Pakistani law at all."
    )
    reason: str = Field(
        description="One short sentence explaining the classification decision."
    )


# ──────────────────────────────────────────────────────────────
# CLASSIFICATION PROMPT
# ──────────────────────────────────────────────────────────────

_INTENT_SYSTEM_PROMPT = """You are a legal query classifier for LegalMind, an AI legal research assistant for Pakistani law.

Your ONLY job is to determine: Is this query related to Pakistani law or not?

Classify the user query into exactly one of:

INTERNAL — The query IS related to Pakistani law. This includes:
- Any Pakistani law, act, section, article, rule, or ordinance
- Punishments, penalties, bail conditions, cognizable / non-cognizable offences
- Legal definitions or court procedures
- Pakistani legal terms: Qatl, Diyat, Qisas, Hadd, Tazir, Zina, Patwari, Intiqal, Fard, Khasra
- Case research, legal precedents, or legal memo generation
- Witness statement comparison
- Asking for links/URLs to LEGAL portals or government law websites (Pakistan Code, Punjab Laws, NALA, SECP, FBR)
- Asking where to download a PDF of a LAW or legal document

EXTERNAL — The query is NOT related to Pakistani law at all. This includes:
- General knowledge, food, entertainment, sports, weather, shopping, travel
- Personal advice unrelated to legal matters
- Non-legal website links, recommendations, or off-topic questions
- Coffee shops, restaurants, cricket, jokes, recipes, etc.
- ANY query that has absolutely no connection to Pakistani law, legal research, or legal procedures

When in doubt, choose INTERNAL.

---
FEW-SHOT EXAMPLES:

Query: "What is the punishment under Section 302 PPC?"
Intent: INTERNAL
Reason: Asking about a specific section and its punishment in Pakistani Penal Code.

Query: "Is Section 20 of PECA bailable or non-bailable?"
Intent: INTERNAL
Reason: Asking about bail classification of a specific law section.

Query: "What does Qatl-i-amd mean in Pakistani law?"
Intent: INTERNAL
Reason: Asking about a Pakistani Urdu legal term and its legal definition.

Query: "Under which court is a murder case tried in Pakistan?"
Intent: INTERNAL
Reason: Asking about court jurisdiction for a criminal offence.

Query: "What are the powers of a Patwari under Punjab Land Revenue Act?"
Intent: INTERNAL
Reason: Asking about a legal role defined in a provincial act.

Query: "Compare the witness statement from hearing 2 and hearing 3."
Intent: INTERNAL
Reason: Asking for witness statement comparison — Jarah Prep task.

Query: "What precedents exist for cybercrime under PECA 2016?"
Intent: INTERNAL
Reason: Asking for case law research related to a specific statute.

Query: "Give me the official link of Pakistan Code website."
Intent: INTERNAL
Reason: Asking for a URL to a government legal portal — law-related.

Query: "Where can I download the PECA 2016 PDF from the official site?"
Intent: INTERNAL
Reason: Asking where to find/download a legal document online — law-related.

Query: "List me 5 coffee shops in Lahore."
Intent: EXTERNAL
Reason: Query is about food/restaurants, completely unrelated to law.

Query: "What is the weather in Karachi today?"
Intent: EXTERNAL
Reason: Query is about weather, has no legal context.

Query: "Who won the cricket match yesterday?"
Intent: EXTERNAL
Reason: Query is about sports, not related to legal research.

Query: "Tell me a joke."
Intent: EXTERNAL
Reason: Query is casual/entertainment, not a legal question.

Query: "Give me links of best coffee shops in Lahore."
Intent: EXTERNAL
Reason: Asking for non-legal website links about restaurants, not related to law.

Query: "What is the best shopping website in Pakistan?"
Intent: EXTERNAL
Reason: Asking for a commercial website recommendation, not a legal query.
---"""


# ──────────────────────────────────────────────────────────────
# INTENT ROUTER NODE
# LangGraph Node 1 — first node in the pipeline graph.
# ──────────────────────────────────────────────────────────────

def intent_router_node(state: LegalMindState) -> dict:
    """
    Reads:   state["user_query"]
    Returns: {"intent", "intent_reason"}
    """
    raw_query = state.get("user_query", "").strip()
    print(f"\n[Intent Router] Query: '{raw_query}'")

    # ── HARD OVERRIDE FOR FRONTEND TOGGLES ──
    # If the user explicitly clicked "Web search" in the frontend, bypass LLM classification
    if raw_query.lower().startswith("web search:"):
        print("[Intent Router] Manual override detected: Forcing EXTERNAL intent due to 'Web search:' prefix.")
        return {
            "intent": "EXTERNAL",
            "intent_reason": "User explicitly clicked the Web Search toggle in the UI."
        }

    try:
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not found in environment!")

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel(CHAT_MODEL)

        full_prompt = f"{_INTENT_SYSTEM_PROMPT}\n\nUser Query: \"{state['user_query']}\""

        # Call Gemini API with JSON response schema
        response = model.generate_content(
            full_prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=IntentClassification,
            )
        )

        # Parse response using Pydantic
        decision = IntentClassification.model_validate_json(response.text)

        print(f"[Intent Router] Intent     : {decision.intent}")
        print(f"[Intent Router] Reason     : {decision.reason}")

        return {
            "intent":            decision.intent,
            "intent_reason":     decision.reason,
        }

    except Exception as e:  
        print(f"[Intent Router] ERROR: {e}")
        return {
            "intent":            "INTERNAL",   # fail-safe default
            "intent_reason":     f"Classification failed: {str(e)}",
        }


# ──────────────────────────────────────────────────────────────
# CONDITIONAL EDGE FUNCTION
# Called by LangGraph after intent_router_node.
# Return value maps to graph edge keys.
# ──────────────────────────────────────────────────────────────

def route_by_intent(state: LegalMindState) -> Literal["external_search", "internal_pipeline"]:
    """
    INTERNAL → "internal_pipeline"  (Query Decomposer Node)
    EXTERNAL → "external_search"    (Web Search Node — has off-topic check built in)
    """
    if state.get("intent") == "EXTERNAL":
        print("[Edge] Routing -> external_search")
        return "external_search"

    print("[Edge] Routing -> internal_pipeline")
    return "internal_pipeline"

