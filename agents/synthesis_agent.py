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
1. **Dynamic Formatting**: 
   - By default, provide a clear, concise, and conversational answer. Use markdown for readability (bullet points, bold text).
   - ONLY IF the user explicitly requests a "formal memo", "detailed memorandum", or similar, you must generate a full, structured legal memo including an Executive Summary, Legal Analysis, and Conclusion.
2. **Citations & Document Links**: 
   - Do NOT insert inline links inside paragraphs or sentences (e.g. do not write "Under [PPC](url)...").
   - Instead, if a paragraph mentions a statute, section, or case (e.g. PPC, CrPC, etc.) that has a local URL, append a citation badge at the very end of that paragraph (or on a new line right below it) in this exact format:
     `\n📌 [Document Name](URL)`
     For example:
     ```
     Under the Pakistan Penal Code, 1860, offenses related to negligent or rash acts are typically addressed under Section 279.
     📌 [Pakistan Penal Code, 1860](http://localhost:8000/api/statutes/PPC.pdf)
     ```
   - If no URL is present in the context, cite it as plain text without any markdown links.
3. **Conflicts**: If different courts have conflicting views, point them out. Supreme Court (SCP) precedents always override High Court precedents.
4. **No Hallucination**: Do NOT invent laws or cases. If the provided context is insufficient to fully answer the query, state clearly what is unknown.
"""

_MEMO_PROMPT = """You are the Senior Legal Synthesis Agent for LegalMind.

Your job is to write a comprehensive, professional, and well-structured legal memo answering the user's queries based on the provided chat history and legal contexts.

## Instructions:
1. **Structure**: Use markdown formatting. Include an Executive Summary, Legal Analysis, and Conclusion. Use proper headers (#, ##).
2. **Citations & Document Links**: 
   - Do NOT insert inline links inside paragraphs or sentences.
   - Instead, if a paragraph mentions a statute, section, or case (e.g. PPC, CrPC, etc.) that has a local URL, append a citation badge at the very end of that paragraph (or on a new line right below it) in this exact format:
     `\n📌 [Document Name](URL)`
     For example:
     ```
     Under the Pakistan Penal Code, 1860, offenses related to negligent or rash acts are typically addressed under Section 279.
     📌 [Pakistan Penal Code, 1860](http://localhost:8000/api/statutes/PPC.pdf)
     ```
   - If no URL is present in the context, cite it as plain text without any markdown links.
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

    def format_context(self, retrieved_results: List[Dict[str, Any]]) -> str:
        """
        Formats the raw retrieved list of dicts into a string block for the LLM.
        """
        if not retrieved_results:
            return "No relevant case laws or statutes were found."

        context_lines = []
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
            
            # Fallback to our local endpoints if no external URL exists
            if not url and file_name != "Unknown File":
                # Ensure the filename is url-encoded (e.g. for spaces)
                import urllib.parse
                safe_filename = urllib.parse.quote(file_name)
                # Check if file exists in Statutes_pipeline/statutes directory
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                local_statute_path = os.path.join(base_dir, "Statutes_pipeline", "statutes", file_name)
                if os.path.exists(local_statute_path):
                    url = f"http://localhost:8000/api/statutes/{safe_filename}"

            text = res.get("text", "").strip()
            score = res.get("score", 0.0)

            header = f"--- Context {idx} [Score: {score:.3f}] ---"
            meta = f"Source: {court} | Year: {year} | Laws: {laws} | File: {file_name}"
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
            "Please answer the query based on the retrieved contexts."
        )
        
        model = self._build_model(system_instruction=_CHAT_PROMPT)
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as exc:
            logger.error("Synthesis generation failed: %s", exc)
            raise RuntimeError(f"Synthesis failed: {exc}") from exc

    def generate_memo_pdf(self, chat_history_str: str, retrieved_results: List[Dict[str, Any]], output_path: str = "legal_memo.pdf") -> str:
        """
        Generates the formal legal memo and saves it directly as a PDF file.
        Returns the absolute path to the PDF.
        """
        logger.info("SynthesisAgent generating formal memo PDF.")
        context_str = self.format_context(retrieved_results)
        
        prompt = (
            f"CHAT HISTORY:\n{chat_history_str}\n\n"
            f"RETRIEVED CONTEXTS FROM CHAT:\n{context_str}\n\n"
            "Please generate a highly formal, comprehensive legal memorandum summarizing the legal analysis based on this chat history and the cited context. Use markdown formatting with # and ## headers. Structure it with an Executive Summary, Legal Analysis, and Conclusion."
        )
        
        model = self._build_model(system_instruction=_MEMO_PROMPT)
        try:
            response = model.generate_content(prompt)
            markdown_content = response.text
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
        response_memo = agent.synthesize(query, retrieved_chunks)
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
