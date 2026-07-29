"""
statute_agent.py — LegalMind Statute Search & RAG Agent (Layer 1)
==================================================================
Handles sub-queries routed to 'statute_agent'.
Generates embeddings, queries the Qdrant 'statutes' collection with metadata filters,
and runs Gemini to generate grounded, cited responses.
"""

import os
import sys
import logging
from typing import List, Dict, Any, Optional

import google.generativeai as genai
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))

from agents.state import LegalMindState
from config import CHAT_MODEL, EMBEDDING_MODEL, VECTOR_SIZE, STATUTES_COLLECTION

load_dotenv()
logger = logging.getLogger(__name__)


def configure_gemini() -> None:
    """Configures the Gemini API key from environment variables."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not found in environment!")
    
    # If multiple keys are provided as comma-separated values, pick the first one
    active_key = api_key.split(",")[0].strip()
    genai.configure(api_key=active_key)


def get_embedding(text: str) -> List[float]:
    """Generates a text embedding vector using Gemini API."""
    configure_gemini()
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=text,
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=VECTOR_SIZE
    )
    return result["embedding"]


def build_qdrant_filter(qdrant_filters: dict, state: LegalMindState) -> qmodels.Filter:
    """
    Translates sub-query filters and global query state (like jurisdiction)
    into a structured Qdrant filter object.
    """
    must_conditions = []

    # 1. Always restrict search to active statute chunks
    must_conditions.append(
        qmodels.FieldCondition(
            key="is_active",
            match=qmodels.MatchValue(value=True)
        )
    )

    # 2. Add global jurisdiction filter if specified in the state
    jurisdiction = state.get("jurisdiction")
    if jurisdiction:
        must_conditions.append(
            qmodels.FieldCondition(
                key="jurisdiction",
                match=qmodels.MatchText(text=jurisdiction)
            )
        )

    # 3. Add sub-query level filters if present
    if qdrant_filters:
        # Year range filter
        year_from = qdrant_filters.get("year_from")
        year_to = qdrant_filters.get("year_to")
        if year_from is not None or year_to is not None:
            range_args = {}
            if year_from is not None:
                range_args["gte"] = int(year_from)
            if year_to is not None:
                range_args["lte"] = int(year_to)
            must_conditions.append(
                qmodels.FieldCondition(
                    key="year",
                    range=qmodels.Range(**range_args)
                )
            )

        # NOTE: laws_cited filter is intentionally SKIPPED here.
        # The decomposer often returns abbreviations (PPC, CrPC, CNIC Act)
        # that don't match the full stored act names (e.g. "Pakistan Penal Code, 1860").
        # Vector similarity search already ranks results by relevance to the query text.

        # Subcategory/case_type filter
        case_type = qdrant_filters.get("case_type")
        if case_type:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="subcategory",
                    match=qmodels.MatchText(text=case_type)
                )
            )

    return qmodels.Filter(must=must_conditions)


def execute_qdrant_search(
    client: QdrantClient,
    query_vector: List[float],
    qfilter: qmodels.Filter,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Performs a vector search on the statutes collection in Qdrant.
    Uses client.query_points() (qdrant-client >= 1.12)."""
    try:
        results = client.query_points(
            collection_name=STATUTES_COLLECTION,
            query=query_vector,
            query_filter=qfilter,
            limit=limit,
            with_payload=True
        )
        
        chunks = []
        for res in results.points:
            payload = res.payload or {}
            chunks.append({
                "point_id": str(res.id),
                "text": payload.get("text", ""),
                "act_name": payload.get("act_name", ""),
                "year": payload.get("year"),
                "jurisdiction": payload.get("jurisdiction", ""),
                "source_file": payload.get("source_file", ""),
                "doc_type": payload.get("doc_type", "statute"),
                "subcategory": payload.get("subcategory", ""),
                "section_number": payload.get("section_number"),
                "section_title": payload.get("section_title", ""),
                "parent_section": payload.get("parent_section"),
                "is_active": payload.get("is_active", True),
                "version": payload.get("version", "v1")
            })
        return chunks
    except Exception as e:
        logger.error("Qdrant search execution error: %s", e)
        print(f"[Statute Agent] Qdrant Search ERROR: {e}")
        return []


def generate_rag_response(query: str, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generates a legally cited answer from Gemini grounded on the retrieved chunks."""
    if not chunks:
        return {
            "answer": "No relevant statute sections were found in the database to answer this question.",
            "citations": []
        }

    configure_gemini()
    model = genai.GenerativeModel(CHAT_MODEL)

    # Build context string
    context_parts = []
    for idx, chunk in enumerate(chunks, 1):
        context_parts.append(
            f"Source #{idx}: {chunk.get('act_name')} ({chunk.get('year') or 'N/A'}), "
            f"Section {chunk.get('section_number') or 'N/A'} - {chunk.get('section_title') or ''}\n"
            f"Jurisdiction: {chunk.get('jurisdiction') or 'Federal'}\n"
            f"Content: {chunk.get('text')}\n"
            f"---"
        )
    context_str = "\n\n".join(context_parts)

    prompt = f"""You are an expert legal assistant for Pakistani law.
Generate a precise, grounded, and professionally written legal answer for the following question using ONLY the provided statute sources.

If the answer cannot be fully answered using the sources, state what is missing but answer as much as possible from the provided text.
Cite the act name and section numbers clearly in your response.

User Question: "{query}"

Retrieved Statutory Sources:
{context_str}

Format your final output as a valid JSON object matching this schema:
{{
  "answer": "<your professional legal response in English>",
  "citations": [
    {{
      "source": "<Act Name, Section Number>",
      "title": "<Section Title or Topic>",
      "text_excerpt": "<exact key sentence or phrase from the source matching the answer>"
    }}
  ]
}}
Return ONLY the raw JSON object. Do not wrap it in markdown code blocks, do not write preamble or commentary.
"""

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        import json
        data = json.loads(response.text.strip())
        return data
    except Exception as e:
        logger.error("Error generating RAG response: %s", e)
        # Fallback response
        citations = []
        for c in chunks[:2]:
            citations.append({
                "source": f"{c.get('act_name')}, Section {c.get('section_number')}",
                "title": c.get('section_title') or "Statute Section",
                "text_excerpt": c.get('text')[:100] + "..."
            })
        return {
            "answer": f"Error generating LLM response: {str(e)}. Raw statutes retrieved: " + 
                      "; ".join([f"{c.get('act_name')} Sec {c.get('section_number')}" for c in chunks]),
            "citations": citations
        }


# ──────────────────────────────────────────────────────────────
# LangGraph Node Function
# ──────────────────────────────────────────────────────────────

def statute_agent_node(state: LegalMindState) -> dict:
    """
    LangGraph Node: Statute Agent.
    Processes all sub-queries targeted to 'statute_agent'.
    """
    sub_queries = state.get("sub_queries") or []
    statute_sub_queries = [sq for sq in sub_queries if sq.get("target_agent") == "statute_agent"]

    if not statute_sub_queries:
        return {}

    print(f"\n[Statute Agent] Active. Processing {len(statute_sub_queries)} sub-query(ies)...")

    # Connect to Qdrant Cloud/Local
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url:
        print("[Statute Agent] ERROR: QDRANT_URL not found in environment!")
        return {"status": "STATUTE_SEARCH_FAILED_CONFIG"}

    # Handle DNS override for Qdrant Cloud if needed
    import socket
    _original_getaddrinfo = socket.getaddrinfo
    def _custom_getaddrinfo(host, port, *args, **kwargs):
        if host == "1f03f5d6-5fc1-441c-9c39-ab06f32a88f9.eu-central-1-0.aws.cloud.qdrant.io":
            return _original_getaddrinfo("3.126.6.235", port, *args, **kwargs)
        return _original_getaddrinfo(host, port, *args, **kwargs)
    socket.getaddrinfo = _custom_getaddrinfo

    try:
        client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=30)
    except Exception as e:
        print(f"[Statute Agent] Connection to Qdrant failed: {e}")
        return {"status": "STATUTE_SEARCH_FAILED_CONNECTION"}

    all_retrieved_chunks = []
    all_citations = []
    answers = []

    for sq in statute_sub_queries:
        query_text = sq.get("query_text")
        qfilters = sq.get("qdrant_filters") or {}
        print(f"  - Query: '{query_text}'")

        try:
            # 1. Embed query text
            query_vector = get_embedding(query_text)
            
            # 2. Build structured Qdrant filter
            qfilter = build_qdrant_filter(qfilters, state)
            
            # 3. Query Qdrant
            chunks = execute_qdrant_search(client, query_vector, qfilter, limit=5)
            print(f"    -> Retrieved {len(chunks)} relevant chunk(s).")
            
            all_retrieved_chunks.extend(chunks)

            # 4. Generate response grounded in source text
            rag_output = generate_rag_response(query_text, chunks)
            answers.append(rag_output.get("answer", ""))
            
            citations = rag_output.get("citations") or []
            all_citations.extend(citations)

        except Exception as e:
            print(f"[Statute Agent] Error processing sub-query {sq.get('id')}: {e}")

    # Combine answers if multiple sub-queries were ran
    combined_answer = "\n\n".join(answers) if answers else "No response generated."

    # Return updates to be merged into the State
    return {
        "retrieved_chunks": all_retrieved_chunks,
        "verified_citations": all_citations,
        "status": "STATUTE_SEARCH_COMPLETED",
        "statute_agent_response": combined_answer  # Optional additional field to store output
    }
