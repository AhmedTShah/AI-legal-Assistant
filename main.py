import os
import sys
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# Ensure the root directory is in the python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.graph import app as graph_app
from agents.state import LegalMindState
from agents.synthesis_agent import SynthesisAgent
from database.memory import save_message, update_session_summary, add_long_term_memory

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI App
app = FastAPI(
    title="LegalMind AI API",
    description="Backend API exposing the LangGraph-based legal research agentic pipeline.",
    version="1.0.0"
)

# Configure CORS Middleware
# Allows React Vite frontend (running on http://localhost:5173 or other local ports) to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve downloads directory statically for PDF links
downloads_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(downloads_path, exist_ok=True)
app.mount("/api/downloads", StaticFiles(directory=downloads_path), name="downloads")

# Serve statutes directory statically for PDF links
statutes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Statutes_pipeline", "statutes")
os.makedirs(statutes_path, exist_ok=True)
app.mount("/api/statutes", StaticFiles(directory=statutes_path), name="statutes")

# Pydantic Schemas for API Contracts
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    user_id: Optional[str] = "lawyer_abc"
    voice_mode: Optional[bool] = False

class ChatHistoryRequest(BaseModel):
    history: str
    retrieved_chunks: List[Dict[str, Any]] = []

class CitationItem(BaseModel):
    source: str
    title: Optional[str] = None
    text_excerpt: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    intent: Optional[str] = None
    detected_language: Optional[str] = None
    primary_legal_issue: Optional[str] = None
    citations: List[Dict[str, Any]] = []
    retrieved_chunks: List[Dict[str, Any]] = []


@app.get("/")
@app.get("/health")
def health_check():
    """Simple health check endpoint."""
    return {
        "status": "healthy",
        "pipeline": "LegalMind LangGraph Orchestrator",
        "qdrant_url": os.getenv("QDRANT_URL", "not set")[:25] + "..."
    }


@app.get("/api/chat/{session_id}")
def get_chat_history(session_id: str):
    """
    Retrieves the chat history (messages) for a given session.
    """
    try:
        from database.memory import get_recent_messages
        messages = get_recent_messages(session_id, limit=50) # Fetch up to 50 messages
        return {"messages": messages}
    except Exception as e:
        logger.error(f"Failed to fetch chat history for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/chat/{session_id}")
def delete_chat_history(session_id: str):
    """
    Deletes all messages for a given session from the database.
    """
    try:
        from database.memory import delete_session_messages
        deleted_count = delete_session_messages(session_id)
        return {"status": "deleted", "session_id": session_id, "deleted_count": deleted_count}
    except Exception as e:
        logger.error(f"Failed to delete chat history for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Core Chat Endpoint. Receives user queries, runs them through the
    LangGraph pipeline (starting with the Intent Router), and returns
    the synthesized legal memo or search results.
    """
    logger.info(f"Received query: {request.message} (Session: {request.session_id}, User: {request.user_id})")

    # 1. Save user query to short-term memory conversations table
    try:
        save_message(request.user_id, request.session_id, "human", request.message)
    except Exception as e:
        logger.warning(f"Failed to persist human message: {e}")

    # Detect case_ref if query mentions "case of X vs Y" or similar
    case_ref = None
    if " vs " in request.message or " versus " in request.message:
        # Simple extraction heuristic for case_ref
        import re
        match = re.search(r"([A-Za-z\s]+ v[s\.]?\s+[A-Za-z\s]+)", request.message, re.IGNORECASE)
        if match:
            case_ref = match.group(1).strip()

    # 2. Initialize the shared state schema with session parameters
    initial_state: LegalMindState = {
        "user_query": request.message,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "case_ref": case_ref,
        "intent": None,
        "intent_reason": None,
        "detected_language": None,
        "requires_urdu_translation": None,
        "primary_legal_issue": None,
        "jurisdiction": None,
        "key_parties": None,
        "statutes_identified": None,
        "sub_queries": None,
        "complexity_score": None,
        "web_search_results": [],
        "status": None,
        "retrieved_chunks": [],
        "verified_citations": [],
        "urdu_terms_found": [],
        "statute_agent_response": None,
        "case_law_agent_response": None,
        "synthesis_response": None
    }

    try:
        # 3. Invoke the compiled LangGraph pipeline
        final_state = graph_app.invoke(initial_state)
        
        # 4. Formulate the response based on the intent result
        intent = final_state.get("intent")
        status = final_state.get("status", "")
        
        if intent == "EXTERNAL" and status == "OFF_TOPIC_QUERY":
            response_text = final_state.get("synthesis_response") or "This query is not related to Pakistani law."
        else:
            response_text = final_state.get("synthesis_response") or "No legal response could be synthesized."

        # 5. Save assistant response to short-term memory conversations table
        try:
            save_message(request.user_id, request.session_id, "assistant", response_text)
        except Exception as e:
            logger.warning(f"Failed to persist assistant message: {e}")

        # 6. Trigger progressive summarization and long-term memory updates
        #    Skip for off-topic queries — no value in saving non-legal chatter to memory
        if status != "OFF_TOPIC_QUERY":
            try:
                update_session_summary(request.session_id)
                add_long_term_memory(request.user_id, request.message, response_text, case_ref=case_ref)
            except Exception as e:
                logger.warning(f"Failed to run progressive summarization or long-term memory sync: {e}")

        return ChatResponse(
            response=response_text,
            intent=intent,
            detected_language=final_state.get("detected_language"),
            primary_legal_issue=final_state.get("primary_legal_issue"),
            citations=final_state.get("verified_citations") or [],
            retrieved_chunks=final_state.get("retrieved_chunks") or []
        )

    except Exception as e:
        logger.error(f"Error during graph execution: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred in the legal pipeline: {str(e)}"
        )


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """
    Streaming Chat Endpoint using Server-Sent Events (SSE).
    Streams Gemini LLM tokens in real-time as they are synthesized.
    """
    logger.info(f"Received streaming query: {request.message} (Session: {request.session_id}, User: {request.user_id})")

    # 1. Save user query to short-term memory
    try:
        save_message(request.user_id, request.session_id, "human", request.message)
    except Exception as e:
        logger.warning(f"Failed to persist human message: {e}")

    # Detect case_ref if query mentions "case of X vs Y" or similar
    case_ref = None
    if " vs " in request.message or " versus " in request.message:
        import re
        match = re.search(r"([A-Za-z\s]+ v[s\.]?\s+[A-Za-z\s]+)", request.message, re.IGNORECASE)
        if match:
            case_ref = match.group(1).strip()

    initial_state: LegalMindState = {
        "user_query": request.message,
        "user_id": request.user_id,
        "session_id": request.session_id,
        "case_ref": case_ref,
        "intent": None,
        "intent_reason": None,
        "detected_language": None,
        "requires_urdu_translation": None,
        "primary_legal_issue": None,
        "jurisdiction": None,
        "key_parties": None,
        "statutes_identified": None,
        "sub_queries": None,
        "complexity_score": None,
        "web_search_results": [],
        "status": None,
        "retrieved_chunks": [],
        "verified_citations": [],
        "urdu_terms_found": [],
        "statute_agent_response": None,
        "case_law_agent_response": None,
        "synthesis_response": None
    }

    async def event_generator():
        try:
            # 2. Invoke the specialist retrieval pipeline
            final_state = graph_app.invoke(initial_state)
            
            intent = final_state.get("intent")
            status = final_state.get("status", "")
            
            if intent == "EXTERNAL" and status == "OFF_TOPIC_QUERY":
                response_text = final_state.get("synthesis_response") or (
                    "I am LegalMind, an AI legal research assistant specialized exclusively in Pakistani law.\n\n"
                    "I provide the following legal services:\n"
                    "- Statute & Act Research\n"
                    "- Case Law & Precedents\n"
                    "- Offense & Bail Classification\n"
                    "- Legal Memo Generation\n\n"
                    "Feel free to ask me anything about Pakistani legal matters, statutes, or court procedures!"
                )
                
                audio_b64 = None
                if request.voice_mode:
                    try:
                        from services.voice_service import PiperTTS
                        piper = PiperTTS()
                        voice_spoken_text = (
                            "I am LegalMind, an AI legal research assistant specialized exclusively in Pakistani law. "
                            "I can assist you with Pakistani statutes, case law precedents, bail classifications, and legal memo generation. "
                            "Feel free to ask me any question about Pakistani legal matters."
                        )
                        audio_b64 = piper.synthesize_to_base64(voice_spoken_text)
                    except Exception as e:
                        logger.warning(f"Off-topic TTS error: {e}")

                payload = {'text': response_text, 'done': True}
                if audio_b64:
                    payload['audio'] = audio_b64

                yield f"data: {json.dumps(payload)}\n\n"
                try:
                    save_message(request.user_id, request.session_id, "assistant", response_text)
                except Exception as e:
                    logger.warning(f"Failed to persist assistant message: {e}")
                return

            retrieved_chunks = final_state.get("retrieved_chunks") or []
            
            query_prompt = request.message
            if request.user_id and request.session_id:
                try:
                    from database.memory import assemble_prompt
                    query_prompt = assemble_prompt(request.user_id, request.session_id, case_ref, request.message)
                except Exception as e:
                    logger.warning(f"Failed to assemble memory prompt: {e}")

            synthesis_agent = SynthesisAgent()
            full_text_list = []
            sentence_buffer = ""
            
            piper = None
            if request.voice_mode:
                try:
                    from services.voice_service import PiperTTS
                    piper = PiperTTS()
                except Exception as e:
                    logger.warning(f"Failed to initialize PiperTTS: {e}")
            
            for chunk in synthesis_agent.synthesize_stream(query_prompt, retrieved_chunks, intent or "INTERNAL"):
                full_text_list.append(chunk)
                
                audio_payload = None
                if request.voice_mode and piper:
                    sentence_buffer += chunk
                    if any(p in chunk for p in [".", "?", "!", "\n"]) and len(sentence_buffer.strip()) > 10:
                        try:
                            audio_payload = piper.synthesize_to_base64(sentence_buffer.strip())
                        except Exception as e:
                            logger.warning(f"Sentence TTS error: {e}")
                        sentence_buffer = ""

                payload = {'text': chunk, 'done': False}
                if audio_payload:
                    payload['audio'] = audio_payload

                yield f"data: {json.dumps(payload)}\n\n"

            if request.voice_mode and piper and sentence_buffer.strip():
                try:
                    final_audio = piper.synthesize_to_base64(sentence_buffer.strip())
                    if final_audio:
                        yield f"data: {json.dumps({'text': '', 'audio': final_audio, 'done': False})}\n\n"
                except Exception:
                    pass

            full_response = "".join(full_text_list)
            
            yield f"data: {json.dumps({'text': '', 'done': True, 'retrieved_chunks': retrieved_chunks})}\n\n"

            # 3. Post-synthesis updates
            if status != "OFF_TOPIC_QUERY":
                try:
                    save_message(request.user_id, request.session_id, "assistant", full_response)
                    update_session_summary(request.session_id)
                    add_long_term_memory(request.user_id, request.message, full_response, case_ref=case_ref)
                except Exception as e:
                    logger.warning(f"Failed to update session memory after stream: {e}")

        except Exception as e:
            logger.error(f"Error during graph execution in stream: {e}")
            yield f"data: {json.dumps({'text': f'An error occurred: {str(e)}', 'done': True})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def cleanup_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        logger.warning(f"Failed to cleanup temp file {path}: {e}")

@app.post("/api/generate_pdf")
async def generate_pdf_endpoint(request: ChatHistoryRequest, background_tasks: BackgroundTasks):
    """
    Takes the full chat history and any accumulated retrieved chunks,
    synthesizes a formal legal memorandum, and returns it as a downloadable PDF.
    """
    try:
        synthesis_agent = SynthesisAgent()
        downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        pdf_path = os.path.join(downloads_dir, f"legal_memo_{os.urandom(4).hex()}.pdf")
        
        # If retrieved_chunks is empty, auto-retrieve using the last user message in history
        retrieved_chunks = request.retrieved_chunks
        if not retrieved_chunks and request.history:
            lines = request.history.split("\n\n")
            last_query = ""
            for block in reversed(lines):
                if block.startswith("USER:"):
                    last_query = block.replace("USER:", "").strip()
                    break
            if last_query:
                logger.info(f"Auto-retrieving context for PDF generation using query: '{last_query}'")
                try:
                    initial_state: LegalMindState = {
                        "user_query": last_query,
                        "web_search_results": [],
                        "retrieved_chunks": [],
                        "verified_citations": [],
                    }
                    final_state = graph_app.invoke(initial_state)
                    retrieved_chunks = final_state.get("retrieved_chunks") or []
                except Exception as exc:
                    logger.warning(f"Failed auto-retrieval for PDF: {exc}")

        # Generate the PDF
        final_path = synthesis_agent.generate_memo_pdf(
            chat_history_str=request.history,
            retrieved_results=retrieved_chunks,
            output_path=pdf_path
        )
        
        # Add a background task to delete the file after it's returned to the client
        background_tasks.add_task(cleanup_file, final_path)
        
        return FileResponse(
            path=final_path, 
            filename="Formal_Legal_Memo.pdf", 
            media_type="application/pdf"
        )
        
    except Exception as e:
        logger.error(f"Error generating PDF memo: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate formal PDF memo: {str(e)}"
        )


@app.post("/api/voice/transcribe")
async def transcribe_audio_endpoint(file: UploadFile = File(...)):
    """
    Accepts an audio file (.webm / .wav / .mp3) from microphone recording,
    transcribes it using faster-whisper (INT8 quantized), and returns the text.
    """
    logger.info(f"Received audio file for transcription: {file.filename} ({file.content_type})")
    try:
        audio_bytes = await file.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Received empty audio file.")
        
        from services.voice_service import WhisperTranscriber
        transcriber = WhisperTranscriber()
        transcribed_text = await asyncio.to_thread(transcriber.transcribe, audio_bytes)
        
        return {
            "status": "success",
            "text": transcribed_text,
            "filename": file.filename
        }
    except Exception as e:
        logger.error(f"Error during audio transcription: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Audio transcription failed: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    # Start the server on localhost:8000 when main.py is run directly
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
