"""
web_search_agent.py — LegalMind Web Search Agent (External Branch Node)
=======================================================================
Pure Dynamic Web Search Agent.
Executes dynamic web search via ddgs (modern DuckDuckGo search library).
No hardcoded portal mappings.
"""

import re
import sys
from typing import List, Dict, Any

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from agents.state import LegalMindState

# Try modern ddgs library first, fallback to duckduckgo_search if needed
try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False


def clean_search_query(raw_query: str) -> str:
    """
    Strips conversational phrases like 'give me the link of', 'where can I find',
    'tell me the website for' so search engine gets clean target search terms.
    """
    cleaned = raw_query.strip()
    
    # Remove common conversational prefixes
    patterns = [
        r'^(?:give\s+me\s+the\s+)?(?:official\s+)?(?:link\s+of|url\s+of|website\s+of|link\s+to|url\s+to|link\s+for|url\s+for)\s+',
        r'^(?:where\s+can\s+i\s+find|where\s+is|how\s+to\s+find)\s+',
        r'^(?:tell\s+me\s+the\s+link\s+for|show\s+me\s+the\s+link\s+for)\s+',
        r'^(?:can\s+you\s+give\s+me\s+the\s+link\s+to)\s+',
    ]
    
    for pat in patterns:
        cleaned = re.sub(pat, '', cleaned, flags=re.IGNORECASE).strip()
        
    return cleaned if cleaned else raw_query


def execute_web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    Executes a dynamic web search for the cleaned query string.
    
    Args:
        query: Raw or cleaned user query string
        max_results: Maximum search results to return (default 3)
        
    Returns:
        List of dicts containing: title, url, snippet
    """
    results = []

    if not HAS_DDG:
        print("[Web Search Agent] Error: 'ddgs' library is not installed.")
        print("[Web Search Agent] Please run: pip install ddgs")
        return [{
            "title": "Library Not Installed",
            "url": "",
            "snippet": "Please install ddgs via pip to enable live web searches."
        }]

    # Clean conversational fluff from query
    search_keywords = clean_search_query(query)

    try:
        with DDGS() as ddgs:
            # First try with cleaned keywords
            ddg_results = list(ddgs.text(search_keywords, max_results=max_results))
            
            # Fallback to raw query if 0 results
            if not ddg_results and search_keywords != query:
                ddg_results = list(ddgs.text(query, max_results=max_results))

            for item in ddg_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", "")
                })
    except Exception as e:
        print(f"[Web Search Agent] Search execution error: {e}")
        results.append({
            "title": "Search Error",
            "url": "",
            "snippet": f"Web search failed: {str(e)}"
        })

    return results


def web_search_node(state: LegalMindState) -> dict:
    """
    LangGraph Node: Web Search Agent
    
    Reads:   state["user_query"]
    Returns: {"web_search_results": [...], "status": "EXTERNAL_SEARCH_COMPLETED"}
             OR polite off-topic refusal if query is not related to law
    """
    raw_query = state.get("user_query", "")
    print(f"\n[Web Search Node] Raw query: '{raw_query}'")

    # ── Off-topic check: is this query about law at all? ──
    legal_keywords = [
        "law", "act", "section", "article", "ordinance", "statute", "legal",
        "court", "judge", "case", "penal", "criminal", "civil", "constitution",
        "ppc", "crpc", "peca", "fir", "bail", "punishment", "qatl", "diyat",
        "qisas", "hadd", "tazir", "zina", "murder", "theft", "fraud",
        "contract", "property", "land", "revenue", "tax", "fbr", "secp",
        "nala", "pakistan code", "punjab laws", "gazette", "regulation",
        "supreme court", "high court", "tribunal", "arbitration", "divorce",
        "custody", "inheritance", "succession", "writ", "petition",
        "advocate", "lawyer", "bar council", "prosecution", "defendant",
        "plaintiff", "judgment", "verdict", "appeal", "revision",
        "patwari", "intiqal", "fard", "khasra", "nikah", "talaq", "khula",
    ]
    query_lower = raw_query.lower()
    is_law_related = any(kw in query_lower for kw in legal_keywords)

    if not is_law_related:
        print("[Web Search Node] Query is OFF-TOPIC — not related to Pakistani law.")
        return {
            "synthesis_response": (
                "I appreciate your query, but I am **LegalMind** — an AI legal research assistant "
                "specialized exclusively in **Pakistani law**.\n\n"
                "I can help you with:\n"
                "- **Legal research** on Pakistani statutes, acts, and ordinances\n"
                "- **Case law analysis** and precedent research\n"
                "- **Punishments, bail conditions**, and procedural classifications\n"
                "- **Legal definitions** and court procedures\n"
                "- **Legal memo generation** for your cases\n\n"
                "Please ask me a question related to Pakistani law, and I'll be happy to assist!"
            ),
            "status": "OFF_TOPIC_QUERY"
        }

    # ── Law-related link request — proceed with web search ──
    search_results = execute_web_search(raw_query, max_results=3)

    print(f"[Web Search Node] Returned {len(search_results)} search result(s):")
    for idx, res in enumerate(search_results, 1):
        print(f"  {idx}. {res['title']} -> {res['url']}")

    return {
        "web_search_results": search_results,
        "status": "EXTERNAL_SEARCH_COMPLETED"
    }

