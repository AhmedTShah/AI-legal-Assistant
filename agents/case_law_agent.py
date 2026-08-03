"""
agents/case_law_agent.py — Case Law Agent for LegalMind Layer 3.
===================================================================
Accepts a structured SubQuery (from the Query Decomposer) and performs
a vector similarity search against the Qdrant `precedents_db`.

Translates QdrantFilters (Pydantic schema) into Qdrant models.Filter.
"""

import logging
from typing import List, Dict, Any

from qdrant_client.http import models as qmodels
from pipeline.qdrant_client import get_qdrant_client
from scraper.utils.embedder import embed_texts
from agents.schemas import SubQuery

logger = logging.getLogger(__name__)

class CaseLawAgent:
    """
    Retrieves relevant court judgment precedents from Qdrant.
    """
    
    def __init__(self, collection_name: str = "precedents_db"):
        self.collection_name = collection_name
        self.client = get_qdrant_client()
        logger.info("CaseLawAgent initialized for collection: %s", self.collection_name)

    def _build_filter(self, sub_query: SubQuery) -> qmodels.Filter:
        """
        Convert the Pydantic QdrantFilters into a native Qdrant Filter object.
        """
        must_conditions = []
        filters = sub_query.qdrant_filters

        # 1. Court filter
        if filters.courts:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="court",
                    match=qmodels.MatchAny(any=[c.value for c in filters.courts])
                )
            )

        # 2. Year filter
        if filters.year_from is not None or filters.year_to is not None:
            range_kwargs = {}
            if filters.year_from is not None:
                range_kwargs["gte"] = filters.year_from
            if filters.year_to is not None:
                range_kwargs["lte"] = filters.year_to
            
            must_conditions.append(
                qmodels.FieldCondition(
                    key="year",
                    range=qmodels.Range(**range_kwargs)
                )
            )

        # 3. Case Type filter
        if filters.case_type:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="case_type",
                    match=qmodels.MatchValue(value=filters.case_type)
                )
            )

        # 4. Laws Cited filter
        if filters.laws_cited:
            must_conditions.append(
                qmodels.FieldCondition(
                    key="laws_cited",
                    match=qmodels.MatchAny(any=filters.laws_cited)
                )
            )

        if not must_conditions:
            return None
        
        return qmodels.Filter(must=must_conditions)

    def search(self, sub_query: SubQuery, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Embed the sub_query text, apply filters, and retrieve top_k chunks.
        
        Returns a list of dicts containing the text and metadata.
        """
        logger.info("CaseLawAgent searching for SubQuery [%s]: '%s'", sub_query.id, sub_query.query_text)
        
        # Embed the query text
        # Using RETRIEVAL_QUERY for search queries
        embeddings = embed_texts([sub_query.query_text], task_type="RETRIEVAL_QUERY")
        if not embeddings:
            logger.warning("Failed to embed query: %s", sub_query.query_text)
            return []
        
        query_vector = embeddings[0]
        
        # Build Qdrant filter
        qdrant_filter = self._build_filter(sub_query)
        
        # Perform cascading searches to guarantee both precision (requested courts) and substance (best semantic matches)
        try:
            all_hits = []
            seen_ids = set()
            
            # 1. Strict filter search
            if qdrant_filter:
                search_results_strict = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=qdrant_filter,
                    limit=top_k,
                    with_payload=True
                )
                for hit in search_results_strict.points:
                    all_hits.append(hit)
                    seen_ids.add(hit.id)
            
            # 2. Relaxed filter search (Preserve only court, drop strict case_type/laws_cited)
            if sub_query.qdrant_filters.courts and len(all_hits) < top_k:
                relaxed_must = [
                    qmodels.FieldCondition(
                        key="court",
                        match=qmodels.MatchAny(any=[c.value for c in sub_query.qdrant_filters.courts])
                    )
                ]
                relaxed_filter = qmodels.Filter(must=relaxed_must)
                search_results_relaxed = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=relaxed_filter,
                    limit=top_k,
                    with_payload=True
                )
                for hit in search_results_relaxed.points:
                    if hit.id not in seen_ids:
                        all_hits.append(hit)
                        seen_ids.add(hit.id)
            
            # 3. Global unfiltered semantic search (Guarantee substantive ratio decidendi even if court cases are procedural)
            search_results_global = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=None,
                limit=top_k,
                with_payload=True
            )
            for hit in search_results_global.points:
                if hit.id not in seen_ids:
                    all_hits.append(hit)
                    seen_ids.add(hit.id)
            
            # Sort by score descending and take top N (allow up to 6 for rich synthesis)
            all_hits.sort(key=lambda x: x.score, reverse=True)
            all_hits = all_hits[:max(top_k, 6)]
            
            # Format results
            formatted_results = []
            for hit in all_hits:
                payload = hit.payload or {}
                formatted_results.append({
                    "sub_query_id": sub_query.id,
                    "score": hit.score,
                    "court": payload.get("court"),
                    "year": payload.get("year"),
                    "source_url": payload.get("source_url"),
                    "laws_cited": payload.get("laws_cited", []),
                    "case_type": payload.get("case_type"),
                    "file_name": payload.get("file_name"),
                    "text": payload.get("text")
                })
                
            logger.info("CaseLawAgent found %d results for SubQuery [%s].", len(formatted_results), sub_query.id)
            return formatted_results
            
        except Exception as exc:
            logger.error("Qdrant search failed for SubQuery [%s]: %s", sub_query.id, exc)
            return []


# ──────────────────────────────────────────────────────────────
# LangGraph Node Function
# ──────────────────────────────────────────────────────────────

from agents.state import LegalMindState
from agents.schemas import SubQuery

def case_law_agent_node(state: LegalMindState) -> dict:
    """
    LangGraph Node: Case Law Agent.
    Processes all sub-queries targeted to 'case_law_agent'.
    """
    sub_queries = state.get("sub_queries") or []
    case_law_sub_queries = [sq for sq in sub_queries if sq.get("target_agent") == "case_law_agent"]

    if not case_law_sub_queries:
        return {}

    print(f"\n[Case Law Agent] Active. Processing {len(case_law_sub_queries)} sub-query(ies)...")

    try:
        agent = CaseLawAgent()
    except Exception as e:
        print(f"[Case Law Agent] Initialization failed: {e}")
        return {"status": "CASE_LAW_INIT_FAILED"}

    all_retrieved_chunks = []
    
    for sq in case_law_sub_queries:
        query_text = sq.get("query_text")
        print(f"  - Query: '{query_text}'")
        try:
            sq_obj = SubQuery(**sq)
            results = agent.search(sq_obj)
            print(f"    -> Retrieved {len(results)} relevant chunk(s).")
            all_retrieved_chunks.extend(results)
        except Exception as e:
            print(f"[Case Law Agent] Error processing sub-query {sq.get('id')}: {e}")

    return {
        "retrieved_chunks": all_retrieved_chunks,
        "status": "CASE_LAW_SEARCH_COMPLETED"
    }
