"""
debug_statute_agent.py — Diagnostic script for Statute Agent pipeline
=====================================================================
Tests each step in isolation to find exactly where the pipeline breaks:
  Step 1: Environment variables (.env)
  Step 2: Qdrant connection + collection info
  Step 3: Gemini embedding generation
  Step 4: Qdrant vector search (the actual query)
  Step 5: RAG response generation via Gemini
"""

import os
import sys
import time
import json
from pathlib import Path

# ── Setup paths ──
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv()

TEST_QUERY = "punishment for theft Pakistan Penal Code"

def step_separator(step_num, title):
    print(f"\n{'='*70}")
    print(f"  STEP {step_num}: {title}")
    print(f"{'='*70}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 1: Check environment variables
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step_separator(1, "Environment Variables")

qdrant_url = os.getenv("QDRANT_URL")
qdrant_api_key = os.getenv("QDRANT_API_KEY")
gemini_key = os.getenv("GEMINI_API_KEY")

print(f"  QDRANT_URL     : {'✅ SET' if qdrant_url else '❌ MISSING'} -> {qdrant_url[:40] + '...' if qdrant_url else 'N/A'}")
print(f"  QDRANT_API_KEY : {'✅ SET' if qdrant_api_key else '❌ MISSING'} -> {qdrant_api_key[:15] + '...' if qdrant_api_key else 'N/A'}")
print(f"  GEMINI_API_KEY : {'✅ SET' if gemini_key else '❌ MISSING'} -> {gemini_key.split(',')[0][:15] + '...' if gemini_key else 'N/A'}")

if not all([qdrant_url, qdrant_api_key, gemini_key]):
    print("\n❌ FATAL: Missing environment variables. Fix .env and re-run.")
    sys.exit(1)

print("\n  ✅ All environment variables loaded.")

from config import STATUTES_COLLECTION, EMBEDDING_MODEL, VECTOR_SIZE, CHAT_MODEL
print(f"\n  Config values:")
print(f"    STATUTES_COLLECTION : {STATUTES_COLLECTION}")
print(f"    EMBEDDING_MODEL     : {EMBEDDING_MODEL}")
print(f"    VECTOR_SIZE         : {VECTOR_SIZE}")
print(f"    CHAT_MODEL          : {CHAT_MODEL}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 2: Qdrant Connection + Collection Info
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step_separator(2, "Qdrant Connection & Collection Info")

# DNS override
import socket
_original_getaddrinfo = socket.getaddrinfo
def _custom_getaddrinfo(host, port, *args, **kwargs):
    if "1f03f5d6" in str(host):
        return _original_getaddrinfo("3.126.6.235", port, *args, **kwargs)
    return _original_getaddrinfo(host, port, *args, **kwargs)
socket.getaddrinfo = _custom_getaddrinfo

from qdrant_client import QdrantClient
from importlib.metadata import version as pkg_version

print(f"  qdrant-client version: {pkg_version('qdrant-client')}")

try:
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, timeout=30)
    collections = [c.name for c in client.get_collections().collections]
    print(f"  ✅ Connected! Collections: {collections}")
    
    if STATUTES_COLLECTION in collections:
        info = client.get_collection(STATUTES_COLLECTION)
        print(f"  ✅ '{STATUTES_COLLECTION}' collection has {info.points_count} points")
        if info.points_count == 0:
            print("  ⚠️  WARNING: Collection is EMPTY — no data to search!")
    else:
        print(f"  ❌ Collection '{STATUTES_COLLECTION}' does NOT exist!")
        sys.exit(1)
except Exception as e:
    print(f"  ❌ Qdrant connection FAILED: {e}")
    sys.exit(1)

# Check which search methods are available
print(f"\n  Available search/query methods on QdrantClient:")
print(f"    .search()        : {'✅ YES' if hasattr(client, 'search') else '❌ NO  <-- THIS IS THE BUG'}")
print(f"    .query_points()  : {'✅ YES' if hasattr(client, 'query_points') else '❌ NO'}")
print(f"    .query()         : {'✅ YES' if hasattr(client, 'query') else '❌ NO'}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 3: Gemini Embedding Generation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step_separator(3, "Gemini Embedding Generation")

import google.generativeai as genai

active_key = gemini_key.split(",")[0].strip()
genai.configure(api_key=active_key)

try:
    t0 = time.time()
    result = genai.embed_content(
        model=EMBEDDING_MODEL,
        content=TEST_QUERY,
        task_type="RETRIEVAL_QUERY",
        output_dimensionality=VECTOR_SIZE
    )
    query_vector = result["embedding"]
    t1 = time.time()
    print(f"  ✅ Embedding generated in {t1-t0:.2f}s")
    print(f"     Vector dim: {len(query_vector)}, first 5 values: {query_vector[:5]}")
except Exception as e:
    print(f"  ❌ Embedding generation FAILED: {e}")
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 4: Qdrant Vector Search
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step_separator(4, "Qdrant Vector Search")

from qdrant_client.http import models as qmodels

# Build a simple filter (is_active=True)
qfilter = qmodels.Filter(must=[
    qmodels.FieldCondition(key="is_active", match=qmodels.MatchValue(value=True))
])

# Test 4a: Try the OLD .search() method (the one statute_agent.py uses)
print("\n  4a) Testing client.search() [OLD API — what statute_agent.py uses]...")
try:
    results = client.search(
        collection_name=STATUTES_COLLECTION,
        query_vector=query_vector,
        query_filter=qfilter,
        limit=5,
        with_payload=True
    )
    print(f"  ✅ client.search() WORKS — got {len(results)} results")
except AttributeError as e:
    print(f"  ❌ client.search() DOES NOT EXIST: {e}")
    print(f"     🔧 FIX: Replace client.search() with client.query_points() in statute_agent.py")
except Exception as e:
    print(f"  ❌ client.search() FAILED with other error: {e}")

# Test 4b: Try the NEW .query_points() method
print("\n  4b) Testing client.query_points() [NEW API — the correct one for qdrant-client v1.18+]...")
try:
    t0 = time.time()
    results = client.query_points(
        collection_name=STATUTES_COLLECTION,
        query=query_vector,
        query_filter=qfilter,
        limit=5,
        with_payload=True
    )
    t1 = time.time()
    
    points = results.points
    print(f"  ✅ client.query_points() WORKS — got {len(points)} results in {t1-t0:.2f}s")
    
    if points:
        print(f"\n  Top results:")
        for i, pt in enumerate(points, 1):
            p = pt.payload or {}
            print(f"    [{i}] Score: {pt.score:.4f}")
            print(f"        Act: {p.get('act_name', 'N/A')}, Section: {p.get('section_number', 'N/A')}")
            print(f"        Text: {p.get('text', '')[:120]}...")
    else:
        print("  ⚠️  No results returned — check if data exists or filters are too strict")
except Exception as e:
    print(f"  ❌ client.query_points() FAILED: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  STEP 5: RAG Response Generation (Gemini)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
step_separator(5, "RAG Response Generation (Gemini)")

try:
    # Use results from query_points if available
    if 'points' in dir() and points:
        chunks = []
        for pt in points:
            p = pt.payload or {}
            chunks.append({
                "act_name": p.get("act_name", ""),
                "year": p.get("year"),
                "section_number": p.get("section_number"),
                "section_title": p.get("section_title", ""),
                "jurisdiction": p.get("jurisdiction", ""),
                "text": p.get("text", ""),
            })
        
        context_parts = []
        for idx, c in enumerate(chunks, 1):
            context_parts.append(
                f"Source #{idx}: {c['act_name']} ({c['year'] or 'N/A'}), "
                f"Section {c['section_number'] or 'N/A'} - {c['section_title']}\n"
                f"Content: {c['text']}\n---"
            )
        context_str = "\n\n".join(context_parts)
        
        model = genai.GenerativeModel(CHAT_MODEL)
        prompt = f"""You are an expert legal assistant. Answer this question using ONLY the provided sources.
        
Question: "{TEST_QUERY}"

Sources:
{context_str}

Respond in JSON: {{"answer": "<response>", "citations": [{{"source": "<act, section>", "text_excerpt": "<key quote>"}}]}}
Return ONLY raw JSON."""

        t0 = time.time()
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.1, response_mime_type="application/json")
        )
        t1 = time.time()
        
        data = json.loads(response.text.strip())
        print(f"  ✅ RAG response generated in {t1-t0:.2f}s")
        print(f"\n  Answer preview: {data.get('answer', '')[:300]}...")
        print(f"  Citations: {len(data.get('citations', []))}")
    else:
        print("  ⏭️  Skipped — no chunks retrieved in Step 4")
except Exception as e:
    print(f"  ❌ RAG generation FAILED: {e}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SUMMARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print(f"\n{'='*70}")
print(f"  DIAGNOSIS SUMMARY")
print(f"{'='*70}")
print(f"""
  qdrant-client version: {pkg_version('qdrant-client')}
  
  In qdrant-client >= 1.12, the .search() method was REMOVED.
  Your statute_agent.py (line 126) calls client.search() which no longer exists.
  
  🔧 FIX REQUIRED in 'Agents/statute_agent.py':
     Replace client.search() with client.query_points()
     The new API uses 'query=' instead of 'query_vector='
     and returns results.points instead of results directly.
""")
