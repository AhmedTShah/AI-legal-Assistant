"""
agents/synthesis_agent.py — Synthesis Agent for LegalMind Layer 3.
===================================================================
Takes the original user query and all retrieved context from specialist agents
(Case Law Agent, Statute Agent) and synthesizes a comprehensive legal memo.
"""

import logging
import os
from typing import List, Dict, Any

import google.generativeai as genai
from dotenv import load_dotenv

from config import CHAT_MODEL

load_dotenv()
logger = logging.getLogger(__name__)


_SYNTHESIS_PROMPT = """You are the Senior Legal Synthesis Agent for LegalMind — an AI-powered legal assistant for Pakistani lawyers.

Your job is to write a comprehensive, professional, and well-structured legal memo answering the user's original query. You must base your answer strictly on the provided legal contexts (case laws, statutes).

## Instructions:
1. **Structure**: Use markdown formatting. Include an Executive Summary, Legal Analysis, and Conclusion.
2. **Citations**: When referencing a retrieved context, cite it clearly. E.g., "(SCP, 2023 - cybercrime_judgment.pdf)". Use the provided `source_url` as a hyperlink if available.
3. **Synthesis**: Do not just list the cases. Synthesize the rules established by them and apply them to the user's query.
4. **Conflicts**: If different courts (e.g., IHC vs LHC) have conflicting views, point them out. Supreme Court (SCP) precedents always override High Court precedents.
5. **Tone**: Objective, professional, analytical.
6. **No Hallucination**: Do NOT invent laws or cases. If the provided context is insufficient to fully answer the query, state clearly what is unknown.

## Inputs:
You will receive:
- The Original User Query
- Retrieved Contexts (formatted text from Qdrant search results)
"""

class SynthesisAgent:
    """
    Synthesizes a final legal memo from retrieved specialist agent contexts.
    """
    def __init__(self, model_name: str = CHAT_MODEL):
        self.model_name = model_name
        self._configure_api()
        logger.info("SynthesisAgent initialized with model: %s", self.model_name)

    def _configure_api(self) -> None:
        """
        Configure the Gemini API key from environment, skipping monthly-capped keys.
        """
        raw_keys_str = os.getenv("GEMINI_API_KEYS", "")
        all_keys = [k.strip() for k in raw_keys_str.split(",") if k.strip()]
        
        single_key = os.getenv("GEMINI_API_KEY", "").strip()
        if single_key and single_key not in all_keys:
            all_keys.insert(0, single_key)

        if not all_keys:
            raise EnvironmentError("No Gemini API key found. Set GEMINI_API_KEY or GEMINI_API_KEYS in .env")

        working_key = None
        for key in all_keys:
            genai.configure(api_key=key)
            try:
                # Quick probe
                genai.embed_content(
                    model="models/gemini-embedding-001",
                    content="ping",
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=1,
                )
                working_key = key
                break
            except Exception as exc:
                err = str(exc).lower()
                if "spend" in err or "monthly" in err:
                    continue
                # Daily quota hit on embedding might still mean chat works, but let's be safe and try next
                working_key = key
                break
                
        if not working_key:
            raise EnvironmentError("All Gemini API keys have exceeded their monthly spending caps.")

        genai.configure(api_key=working_key)

    def _build_model(self) -> genai.GenerativeModel:
        return genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=_SYNTHESIS_PROMPT,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )

    def format_context(self, retrieved_results: List[Dict[str, Any]]) -> str:
        """
        Formats the raw retrieved list of dicts into a string block for the LLM.
        """
        if not retrieved_results:
            return "No relevant case laws or statutes were found."

        context_lines = []
        for idx, res in enumerate(retrieved_results, start=1):
            court = res.get("court", "Unknown Court")
            year = res.get("year", "Unknown Year")
            laws = ", ".join(res.get("laws_cited") or [])
            file_name = res.get("file_name", "Unknown File")
            url = res.get("source_url", "")
            text = res.get("text", "").strip()
            score = res.get("score", 0.0)

            header = f"--- Context {idx} [Score: {score:.3f}] ---"
            meta = f"Court: {court} | Year: {year} | Laws: {laws} | File: {file_name}"
            if url:
                meta += f" | URL: {url}"
            
            context_lines.append(f"{header}\n{meta}\nText:\n{text}\n")
            
        return "\n".join(context_lines)

    def synthesize(self, original_query: str, retrieved_results: List[Dict[str, Any]]) -> str:
        """
        Generates the final legal memo.
        """
        logger.info("SynthesisAgent generating memo for query: '%s'", original_query)
        context_str = self.format_context(retrieved_results)
        
        prompt = (
            f"USER QUERY:\n{original_query}\n\n"
            f"RETRIEVED CONTEXTS:\n{context_str}\n\n"
            "Please generate the final legal memo based on the above."
        )
        
        model = self._build_model()
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:
            logger.error("Synthesis generation failed: %s", exc)
            raise RuntimeError(f"Synthesis failed: {exc}") from exc


# ──────────────────────────────────────────────────────────────
# LangGraph Node Function
# ──────────────────────────────────────────────────────────────

from Agents.state import LegalMindState

def synthesis_agent_node(state: LegalMindState) -> dict:
    """
    LangGraph Node: Synthesis Agent.
    Aggregates all retrieved chunks (from statutes and precedents) and generates
    the final legally cited response memo.
    """
    retrieved_chunks = state.get("retrieved_chunks") or []
    
    print(f"\n[Synthesis Agent] Active. Synthesizing {len(retrieved_chunks)} source chunk(s)...")

    try:
        agent = SynthesisAgent()
        response_memo = agent.synthesize(state.get("user_query", ""), retrieved_chunks)
        print("[Synthesis Agent] Final legal memo generated successfully.")
        return {
            "synthesis_response": response_memo,
            "status": "SYNTHESIS_COMPLETED"
        }
    except Exception as e:
        print(f"[Synthesis Agent] Error during synthesis: {e}")
        return {
            "synthesis_response": f"Failed to synthesize final legal memo due to error: {str(e)}",
            "status": "SYNTHESIS_FAILED"
        }
