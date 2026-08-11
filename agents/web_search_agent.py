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
    
    # Remove common conversational prefixes and frontend toggle prefixes
    patterns = [
        r'^web\s+search:\s*',
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
    """
    results = []
    
    # Dynamically import to pick up newly installed libraries without a server restart
    DDGS = None
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            pass

    if DDGS is None:
        print("[Web Search Agent] Error: 'ddgs' library is not installed.")
        print("[Web Search Agent] Please run: pip install duckduckgo-search")
        return [{
            "title": "Library Not Installed",
            "url": "",
            "snippet": "Please install ddgs via pip to enable live web searches."
        }]

    # Clean conversational fluff from query
    search_keywords = clean_search_query(query)
    
    # Force Pakistan context if missing
    if "pakistan" not in search_keywords.lower():
        search_keywords += " Pakistan"

    print(f"[Web Search Debug] Cleaned keywords: '{search_keywords}'")

    try:
        with DDGS() as ddgs:
            # First try with cleaned keywords
            ddg_results = list(ddgs.text(search_keywords, region='pk-en', max_results=max_results))
            
            # Fallback to raw query if 0 results
            if not ddg_results and search_keywords != query:
                fallback_query = query
                if "pakistan" not in fallback_query.lower():
                    fallback_query += " Pakistan"
                print(f"[Web Search Debug] Fallback query: '{fallback_query}'")
                ddg_results = list(ddgs.text(fallback_query, region='pk-en', max_results=max_results))

            for item in ddg_results:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("href", ""),
                    "snippet": item.get("body", "")
                })
                
            if not results:
                # Debugging info if 0 results returned
                import pkg_resources
                try:
                    v = pkg_resources.get_distribution("ddgs").version
                except:
                    v = "Unknown"
                results.append({
                    "title": "No Results Found (Debugging)",
                    "url": "",
                    "snippet": f"DDG returned 0 results. Keywords: '{search_keywords}', ddgs version: {v}"
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
                "I am **LegalMind**, an AI legal research assistant specialized exclusively in **Pakistani law**.\n\n"
                "**I provide the following legal services:**\n"
                "- **Statute & Act Research**: Detailed information on Pakistani laws, acts, ordinances, PPC sections, and CrPC procedures.\n"
                "- **Case Law & Precedents**: Finding relevant Supreme Court and High Court judgments and legal precedents.\n"
                "- **Offense & Bail Classification**: Guidance on bailable/non-bailable offenses, punishments, and court jurisdictions.\n"
                "- **Legal Portals & Document Links**: Official links and resources for downloading law PDFs and statutes.\n"
                "- **Legal Memo Generation**: Automated structuring of legal research memos for lawyers and legal professionals.\n\n"
                "Feel free to ask me anything about Pakistani legal statutes, case precedents, court procedures, or legal advice!"
            ),
            "status": "OFF_TOPIC_QUERY"
        }

    # ── Law-related link request — proceed with web search ──
    search_results = execute_web_search(raw_query, max_results=3)

    print(f"[Web Search Node] Returned {len(search_results)} search result(s):")
    retrieved_chunks = []
    for idx, res in enumerate(search_results, 1):
        print(f"  {idx}. {res['title']} -> {res['url']}")
        retrieved_chunks.append({
            "court": "Unknown Court",
            "year": "2024",
            "file_name": res["title"],
            "source_url": res["url"],
            "text": res["snippet"]
        })

    return {
        "web_search_results": search_results,
        "retrieved_chunks": retrieved_chunks,
        "status": "EXTERNAL_SEARCH_COMPLETED"
    }

