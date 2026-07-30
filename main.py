import os
import sys
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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

# Pydantic Schemas for API Contracts
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    user_id: Optional[str] = "lawyer_abc"

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
        
        if intent == "EXTERNAL":
            web_results = final_state.get("web_search_results") or []
            if web_results:
                response_text = "Here are the top results from the web:\n\n"
                for idx, res in enumerate(web_results, 1):
                    response_text += f"{idx}. **[{res.get('title')}]({res.get('url')})**\n{res.get('snippet')}\n\n"
            else:
                response_text = "External web search was triggered but no results were retrieved."
        else:
            response_text = final_state.get("synthesis_response") or "No legal response could be synthesized."

        # 5. Save assistant response to short-term memory conversations table
        try:
            save_message(request.user_id, request.session_id, "assistant", response_text)
        except Exception as e:
            logger.warning(f"Failed to persist assistant message: {e}")

        # 6. Trigger progressive summarization and long-term memory updates
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
    logger.info("Received request to generate formal PDF memo.")
    
    try:
        synthesis_agent = SynthesisAgent()
        # Ensure downloads dir exists
        downloads_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        
        pdf_path = os.path.join(downloads_dir, f"legal_memo_{os.urandom(4).hex()}.pdf")
        
        # Generate the PDF
        final_path = synthesis_agent.generate_memo_pdf(
            chat_history_str=request.history,
            retrieved_results=request.retrieved_chunks,
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


if __name__ == "__main__":
    import uvicorn
    # Start the server on localhost:8000 when main.py is run directly
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
