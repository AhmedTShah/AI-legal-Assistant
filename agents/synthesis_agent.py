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


_CHAT_PROMPT = """You are LegalMind, an AI-powered legal assistant for Pakistani lawyers.

Your job is to answer the user's query based strictly on the provided legal contexts (case laws, statutes).

## Instructions:
1. **Response Structure & Formatting**:
   - Provide an exhaustive, highly detailed, and comprehensive legal explanation. Aim to write a long, thorough response (typically 150-350 words depending on query complexity, though simpler queries can be shorter) with all possible points, exceptions, and procedural nuances fully explained. Do not write brief or concise summaries.
   - Categorize the implications clearly (e.g. explain General offense details, Aggravated conditions/exceptions, and Procedural Classifications like Bail status, Compounding, and Jurisdiction in detail).
   - Use bullet points and bold text for readability.
   - ONLY IF the user explicitly requests a "formal memo", "detailed memorandum", or similar, you must generate a full, structured legal memo including an Executive Summary, Legal Analysis, and Conclusion.
2. **Citations & Document Links**:
   - DO NOT insert markdown links inside sentences.
   - At the very end of a sentence or paragraph that references a context block, you MUST append the exact `Citation to use:` string provided in that context block's metadata.
   - Do NOT use emojis (like 📌) or put the citation on a new line. It must be inline, right at the end of the sentence.
3. **Conflicts**: If different courts have conflicting views, point them out. Supreme Court (SCP) precedents always override High Court precedents.
4. **No Hallucination**: Do NOT invent laws or cases. If the provided context is insufficient to fully answer the query, state clearly what is unknown.
"""

_MEMO_PROMPT = """You are the Senior Legal Synthesis Agent for LegalMind.

Your job is to write a comprehensive, professional, and well-structured legal memo answering the user's queries based on the provided chat history and legal contexts.

## Instructions:
1. **Structure**: Use markdown formatting. Include an Executive Summary, Legal Analysis, and Conclusion. Use proper headers (#, ##).
2. **Citations & Document Links**:
   - DO NOT insert markdown links inside sentences.
   - At the very end of a sentence or paragraph that references a context block, you MUST append the exact `Citation to use:` string provided in that context block's metadata.
   - Do NOT use emojis (like 📌) or put the citation on a new line. It must be inline, right at the end of the sentence.
3. **Synthesis**: Synthesize the rules established by the cases and apply them to the user's situation.
4. **Tone**: Objective, professional, analytical.
5. **No Hallucination**: Do NOT invent laws or cases.
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

    def _build_model(self, system_instruction: str) -> genai.GenerativeModel:
        return genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_instruction,
            generation_config=genai.GenerationConfig(
                temperature=0.3,
                max_output_tokens=4096,
            ),
        )

    def format_context(self, retrieved_results: List[Dict[str, Any]]) -> tuple[str, Dict[str, str]]:
        """
        Formats the raw retrieved list of dicts into a string block for the LLM.
        Returns a tuple of (context_string, context_map) where context_map is used for post-generation replacement.
        """
        if not retrieved_results:
            return "No relevant case laws or statutes were found.", {}

        context_lines = []
        context_map = {}
        for idx, res in enumerate(retrieved_results, start=1):
            court = res.get("court", res.get("jurisdiction", "Unknown Court/Jurisdiction"))
            year = res.get("year", "Unknown Year")
            # Statutes often use act_name and section_number instead of laws_cited
            act_name = res.get("act_name")
            section = res.get("section_number")
            if act_name and section:
                laws = f"{act_name}, Sec {section}"
            else:
                laws = ", ".join(res.get("laws_cited") or [])
                
            # Statutes use source_file instead of file_name
            file_name = res.get("file_name") or res.get("source_file") or "Unknown File"
            url = res.get("source_url", "")
            
            # Unconditionally generate local endpoints if no external URL exists
            if not url and file_name != "Unknown File":
                import urllib.parse
                safe_filename = urllib.parse.quote(file_name)
                
                # Check if it's a statute vs case law based on court/act_name or path
                is_statute = bool(act_name) or "Statutes_pipeline" in file_name or file_name.endswith((".txt", ".md"))
                if is_statute:
                    url = f"http://localhost:8000/api/statutes/{safe_filename}"
                else:
                    url = f"http://localhost:8000/api/downloads/{safe_filename}"

            # Construct a meaningful abbreviation for the citation
            if act_name:
                if section:
                    abbrev = f"{act_name}, Sec {section}"
                else:
                    abbrev = act_name
            else:
                abbrev = f"{court} {year}" if "Unknown" not in court else file_name.replace(".pdf", "")
                if len(abbrev) > 25:
                    abbrev = abbrev[:25] + "..."
            
            # Make abbreviation unique to avoid URL collisions if multiple cases have same court/year
            original_abbrev = abbrev
            counter = 1
            while f"[{abbrev}]" in context_map:
                abbrev = f"{original_abbrev} {chr(96+counter)}" # e.g. ihc 2024 a
                counter += 1
            
            placeholder = f"[{abbrev}]"
            citation_str = f"[{abbrev}]({url})" if url else f"[{abbrev}]"
            context_map[placeholder] = citation_str

            text = res.get("text", "").strip()
            score = res.get("score", 0.0)

            header = f"--- Context {idx} [Score: {score:.3f}] ---"
            meta = f"Citation to use: {placeholder}\nSource: {court} | Year: {year} | Laws: {laws} | File: {file_name}"
            if url:
                meta += f" | URL: {url}"
            
            context_lines.append(f"{header}\n{meta}\nText:\n{text}\n")
            
        return "\n".join(context_lines), context_map

    def synthesize(self, original_query: str, retrieved_results: List[Dict[str, Any]], intent: str = "INTERNAL") -> str:
        """
        Generates the final legal memo or web search summary.
        """
        logger.info("SynthesisAgent generating response for query: '%s' (Intent: %s)", original_query, intent)
        context_str, context_map = self.format_context(retrieved_results)
        
        prompt = (
            f"USER QUERY:\n{original_query}\n\n"
            f"RETRIEVED CONTEXTS:\n{context_str}\n\n"
            "Please answer the query based on the retrieved contexts."
        )
        
        if intent == "EXTERNAL":
            _WEB_SEARCH_PROMPT = """You are LegalMind, an AI legal assistant. The user has just run a live web search.
Your job is to read the retrieved web search snippets and provide a helpful, natural, and conversational summary answering the user's question. 
DO NOT act like a rigid offline database. If the user asks why you can't search a specific archive, politely explain your current capabilities.
Always append the exact `Citation to use:` string provided in the context blocks to cite your sources inline.
"""
            model = self._build_model(system_instruction=_WEB_SEARCH_PROMPT)
        else:
            model = self._build_model(system_instruction=_CHAT_PROMPT)

        try:
            response_text = model.generate_content(prompt).text
            # Inject actual links after LLM generates text to prevent URL stripping
            import re
            for placeholder, actual_citation in context_map.items():
                abbrev = placeholder[1:-1] # strip the [ and ] to get raw abbrev
                pattern = r'\[\s*' + re.escape(abbrev) + r'\s*\]|' + re.escape(abbrev)
                response_text = re.sub(pattern, actual_citation, response_text)
            return response_text
        except Exception as exc:
            logger.error("Synthesis generation failed: %s", exc)
            raise RuntimeError(f"Synthesis failed: {exc}") from exc

    def synthesize_stream(self, original_query: str, retrieved_results: List[Dict[str, Any]], intent: str = "INTERNAL"):
        """
        Generates the final legal response as a generator yielding text chunks in real-time.
        """
        logger.info("SynthesisAgent generating streaming response for query: '%s' (Intent: %s)", original_query, intent)
        context_str, context_map = self.format_context(retrieved_results)
        
        prompt = (
            f"USER QUERY:\n{original_query}\n\n"
            f"RETRIEVED CONTEXTS:\n{context_str}\n\n"
            "Please answer the query based on the retrieved contexts."
        )
        
        if intent == "EXTERNAL":
            _WEB_SEARCH_PROMPT = """You are LegalMind, an AI legal assistant. The user has just run a live web search.
Your job is to read the retrieved web search snippets and provide a helpful, natural, and conversational summary answering the user's question. 
DO NOT act like a rigid offline database. If the user asks why you can't search a specific archive, politely explain your current capabilities.
Always append the exact `Citation to use:` string provided in the context blocks to cite your sources inline.
"""
            model = self._build_model(system_instruction=_WEB_SEARCH_PROMPT)
        else:
            model = self._build_model(system_instruction=_CHAT_PROMPT)

        try:
            import re
            response = model.generate_content(prompt, stream=True)
            for chunk in response:
                if chunk.text:
                    text_chunk = chunk.text
                    for placeholder, actual_citation in context_map.items():
                        abbrev = placeholder[1:-1]
                        pattern = r'\[\s*' + re.escape(abbrev) + r'\s*\]|' + re.escape(abbrev)
                        text_chunk = re.sub(pattern, actual_citation, text_chunk)
                    yield text_chunk
        except Exception as exc:
            logger.error("Synthesis streaming failed: %s", exc)
            yield f"\n[Synthesis failed: {str(exc)}]"

    def generate_memo_pdf(self, chat_history_str: str, retrieved_results: List[Dict[str, Any]], output_path: str = "legal_memo.pdf") -> str:
        """
        Generates the formal legal memo and saves it directly as a PDF file.
        Returns the absolute path to the PDF.
        """
        logger.info("SynthesisAgent generating formal memo PDF.")
        context_str, context_map = self.format_context(retrieved_results)
        
        prompt = (
            f"CHAT HISTORY:\n{chat_history_str}\n\n"
            f"RETRIEVED CONTEXTS FROM CHAT:\n{context_str}\n\n"
            "Please generate a highly formal, comprehensive legal memorandum summarizing the legal analysis based on this chat history and the cited context. Use markdown formatting with # and ## headers. Structure it with an Executive Summary, Legal Analysis, and Conclusion."
        )
        
        model = self._build_model(system_instruction=_MEMO_PROMPT)
        try:
            response_text = model.generate_content(prompt).text
            for placeholder, actual_citation in context_map.items():
                response_text = response_text.replace(placeholder, actual_citation)
            markdown_content = response_text
        except Exception as exc:
            logger.error("Memo text generation failed: %s", exc)
            raise RuntimeError(f"Memo text generation failed: {exc}") from exc
            
        # Convert Markdown to PDF
        try:
            from markdown_pdf import Section, MarkdownPdf
            pdf = MarkdownPdf(toc_level=0) # No TOC needed for short memos
            pdf.add_section(Section(markdown_content))
            pdf.save(output_path)
            logger.info("Saved formal memo PDF to: %s", output_path)
            return os.path.abspath(output_path)
        except Exception as exc:
            logger.error("PDF generation failed: %s", exc)
            raise RuntimeError(f"PDF generation failed: {exc}") from exc



# ──────────────────────────────────────────────────────────────
# LangGraph Node Function
# ──────────────────────────────────────────────────────────────

from agents.state import LegalMindState

def synthesis_agent_node(state: LegalMindState) -> dict:
    """
    LangGraph Node: Synthesis Agent.
    Aggregates all retrieved chunks (from statutes and precedents) and generates
    the final legally cited response memo.
    """
    retrieved_chunks = state.get("retrieved_chunks") or []
    
    print(f"\n[Synthesis Agent] Active. Synthesizing {len(retrieved_chunks)} source chunk(s)...")

    user_id = state.get("user_id")
    session_id = state.get("session_id")
    case_ref = state.get("case_ref")
    query = state.get("user_query", "")

    if user_id and session_id:
        try:
            from database.memory import assemble_prompt
            query = assemble_prompt(user_id, session_id, case_ref, query)
            print("[Synthesis Agent] Assembled prompt with long-term memory & short-term summary contexts.")
        except Exception as e:
            print(f"[Synthesis Agent] Warning: Failed to assemble prompt memory contexts: {e}")

    try:
        agent = SynthesisAgent()
        intent = state.get("intent", "INTERNAL")
        response_memo = agent.synthesize(query, retrieved_chunks, intent)
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
