# database/memory.py
"""
database/memory.py — Complete Memory Management System for LegalMind
===================================================================
Manages short-term conversation logs (with progressive summarization) 
and long-term vector-based facts using PostgreSQL, pgvector, and Mem0.
"""

import os
# Disable Mem0 telemetry to prevent background thread locks and speed up operations
os.environ["MEM0_TELEMETRY"] = "false"

import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any, Tuple, Optional
import google.generativeai as genai
from mem0 import Memory


from dotenv import load_dotenv
load_dotenv()

from config import (
    CHAT_MODEL, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD,
    MEM0_LLM_PROVIDER, MEM0_LLM_MODEL, MEM0_EMBEDDER_PROVIDER, MEM0_EMBEDDING_MODEL
)



logger = logging.getLogger(__name__)

# PostgreSQL Configuration
POSTGRES_HOST = os.getenv("POSTGRES_HOST", POSTGRES_HOST)
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", str(POSTGRES_PORT)))
POSTGRES_DB = os.getenv("POSTGRES_DB", POSTGRES_DB)
POSTGRES_USER = os.getenv("POSTGRES_USER", POSTGRES_USER)
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", POSTGRES_PASSWORD)

# Singleton Mem0 Client
_memory_client: Optional[Memory] = None


def get_db_connection(connect_db: bool = True) -> psycopg2.extensions.connection:
    """Returns a psycopg2 connection to PostgreSQL."""
    dbname = POSTGRES_DB if connect_db else "postgres"
    conn = psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        dbname=dbname,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD
    )
    return conn


def initialize_db() -> None:
    """
    Initializes the PostgreSQL database, enabling pgvector extension,
    creating conversations table, long_term_memory table with custom columns,
    and setting up Mem0 internal synchronization.
    """
    logger.info("Initializing LegalMind Database Schema...")
    
    # 1. Ensure target database exists
    try:
        conn = get_db_connection(connect_db=False)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{POSTGRES_DB}'")
            exists = cur.fetchone()
            if not exists:
                logger.info(f"Database '{POSTGRES_DB}' does not exist. Creating...")
                cur.execute(f"CREATE DATABASE {POSTGRES_DB}")
                logger.info(f"Database '{POSTGRES_DB}' created successfully.")
        conn.close()
    except Exception as e:
        logger.error(f"Error checking/creating database '{POSTGRES_DB}': {e}")

    # 2. Enable pgvector and create tables/triggers
    try:
        conn = get_db_connection(connect_db=True)
        conn.autocommit = True
        
        # Determine embedding dimension based on active provider
        dim = 1536 if os.getenv("OPENAI_API_KEY") else 768
        logger.info(f"Configuring vector columns with dimension: {dim}")

        with conn.cursor() as cur:
            # Enable pgvector extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # Create conversations (short-term memory) table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          SERIAL PRIMARY KEY,
                    user_id     VARCHAR(255) NOT NULL,
                    session_id  VARCHAR(255) NOT NULL,
                    role        VARCHAR(10) NOT NULL,  -- 'human' or 'ai'
                    content     TEXT NOT NULL,
                    summary     TEXT DEFAULT NULL,     -- session summary
                    timestamp   TIMESTAMP DEFAULT NOW()
                );
            """)
            logger.info("Short-term conversations table initialized.")

            # Create long_term_memory (long-term memory) table with exact user columns
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id          SERIAL PRIMARY KEY,
                    user_id     VARCHAR(255) NOT NULL,
                    category    VARCHAR(50) NOT NULL,  -- 'case' / 'argument' / 'preference' / 'client' / 'research'
                    content     TEXT NOT NULL,         -- extracted fact
                    embedding   vector({dim}),          -- pgvector column
                    case_ref    VARCHAR(255),          -- "Ahmed vs National Bank"
                    created_at  TIMESTAMP DEFAULT NOW(),
                    updated_at  TIMESTAMP DEFAULT NOW()
                );
            """)
            logger.info("Custom long-term memory table initialized.")

            # Create Mem0 internal storage table to attach triggers
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS mem0_memory (
                    id          UUID PRIMARY KEY,
                    vector      vector({dim}),
                    payload     JSONB
                );
            """)
            logger.info("Mem0 internal table initialized.")

            # Create categorization helper function
            cur.execute("""
                CREATE OR REPLACE FUNCTION categorize_memory(content TEXT)
                RETURNS VARCHAR(50) AS $$
                DECLARE
                    lower_content TEXT;
                BEGIN
                    lower_content := LOWER(content);
                    IF lower_content LIKE '%prefer%' OR lower_content LIKE '%like%' OR lower_content LIKE '%want%' OR lower_content LIKE '%choose%' OR lower_content LIKE '%always%' THEN
                        RETURN 'preference';
                    ELSIF lower_content LIKE '%case%' OR lower_content LIKE '%vs%' OR lower_content LIKE '%versus%' OR lower_content LIKE '%court%' OR lower_content LIKE '%judgment%' OR lower_content LIKE '%ahmed%' THEN
                        RETURN 'case';
                    ELSIF lower_content LIKE '%argument%' OR lower_content LIKE '%claim%' OR lower_content LIKE '%dispute%' OR lower_content LIKE '%foreseeable%' OR lower_content LIKE '%force majeure%' THEN
                        RETURN 'argument';
                    ELSIF lower_content LIKE '%client%' OR lower_content LIKE '%customer%' OR lower_content LIKE '%party%' THEN
                        RETURN 'client';
                    ELSE
                        RETURN 'research';
                    END IF;
                END;
                $$ LANGUAGE plpgsql;
            """)

            # Create synchronization trigger function
            cur.execute("""
                CREATE OR REPLACE FUNCTION sync_mem0_to_long_term()
                RETURNS TRIGGER AS $$
                BEGIN
                    IF (TG_OP = 'INSERT') THEN
                        INSERT INTO long_term_memory (user_id, category, content, embedding, case_ref, created_at, updated_at)
                        VALUES (
                            NEW.payload->>'user_id',
                            categorize_memory(NEW.payload->>'data'),
                            NEW.payload->>'data',
                            NEW.vector,
                            NEW.payload->>'case_ref',
                            NOW(),
                            NOW()
                        );
                    ELSIF (TG_OP = 'UPDATE') THEN
                        UPDATE long_term_memory
                        SET 
                            category = categorize_memory(NEW.payload->>'data'),
                            content = NEW.payload->>'data',
                            embedding = NEW.vector,
                            case_ref = NEW.payload->>'case_ref',
                            updated_at = NOW()
                        WHERE user_id = OLD.payload->>'user_id' AND content = OLD.payload->>'data';
                    ELSIF (TG_OP = 'DELETE') THEN
                        DELETE FROM long_term_memory
                        WHERE user_id = OLD.payload->>'user_id' AND content = OLD.payload->>'data';
                    END IF;
                    RETURN NULL;
                END;
                $$ LANGUAGE plpgsql;
            """)

            # Attach trigger to mem0_memory
            cur.execute("""
                DROP TRIGGER IF EXISTS trg_sync_mem0_memory ON mem0_memory;
                CREATE TRIGGER trg_sync_mem0_memory
                AFTER INSERT OR UPDATE OR DELETE ON mem0_memory
                FOR EACH ROW EXECUTE FUNCTION sync_mem0_to_long_term();
            """)
            logger.info("Real-time trigger-based memory synchronization established.")

        conn.close()
    except Exception as e:
        logger.error(f"Error during schema initialization: {e}")
        raise e



def get_mem0_client() -> Memory:
    """
    Initializes and returns the singleton Mem0 Memory client.
    Configured using parameters centralized in config.py.
    """
    global _memory_client
    if _memory_client is not None:
        return _memory_client

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    # Select the appropriate API key based on config.py provider
    llm_key = openai_key if MEM0_LLM_PROVIDER == "openai" else gemini_key
    embedder_key = openai_key if MEM0_EMBEDDER_PROVIDER == "openai" else gemini_key

    if not llm_key or not embedder_key:
        raise ValueError("API key for the configured Mem0 LLM/Embedder provider is missing in environment variables!")

    # Set dimensions dynamically based on config.py embedder provider
    dims = 1536 if MEM0_EMBEDDER_PROVIDER == "openai" else 768

    logger.info(f"Configuring Mem0 (LLM: {MEM0_LLM_PROVIDER}/{MEM0_LLM_MODEL}, Embedder: {MEM0_EMBEDDER_PROVIDER}/{MEM0_EMBEDDING_MODEL})")
    
    config = {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "host": POSTGRES_HOST,
                "port": POSTGRES_PORT,
                "dbname": POSTGRES_DB,
                "user": POSTGRES_USER,
                "password": POSTGRES_PASSWORD,
                "collection_name": "mem0_memory",
                "embedding_model_dims": dims
            }
        },
        "llm": {
            "provider": MEM0_LLM_PROVIDER,
            "config": {
                "model": MEM0_LLM_MODEL,
                "api_key": llm_key
            }
        },
        "embedder": {
            "provider": MEM0_EMBEDDER_PROVIDER,
            "config": {
                "model": MEM0_EMBEDDING_MODEL,
                "api_key": embedder_key
            }
        }
    }

    # Initialize Mem0 client
    _memory_client = Memory.from_config(config)
    return _memory_client


# =====================================================================
# SHORT-TERM MEMORY FUNCTIONS
# =====================================================================

def save_message(user_id: str, session_id: str, role: str, content: str) -> None:
    """
    Saves a message to the database conversations archive.
    """
    try:
        conn = get_db_connection(connect_db=True)
        with conn.cursor() as cur:
            # 1. Fetch current session's latest summary if it exists
            cur.execute(
                "SELECT summary FROM conversations WHERE session_id = %s AND summary IS NOT NULL LIMIT 1;",
                (session_id,)
            )
            res = cur.fetchone()
            current_summary = res[0] if res else None

            # 2. Insert the new message
            cur.execute(
                "INSERT INTO conversations (user_id, session_id, role, content, summary) VALUES (%s, %s, %s, %s, %s);",
                (user_id, session_id, role, content, current_summary)
            )
            conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save message to conversations database: {e}")
        raise e


def get_recent_messages(session_id: str, limit: int = 10) -> List[Dict[str, str]]:
    """
    Fetches the last N messages of a session. Returns a list in chronological order.
    """
    try:
        conn = get_db_connection(connect_db=True)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT role, content FROM conversations WHERE session_id = %s ORDER BY timestamp DESC LIMIT %s;",
                (session_id, limit)
            )
            rows = cur.fetchall()
        conn.close()
        # Reverse to return in chronological order
        return list(reversed(rows))
    except Exception as e:
        logger.error(f"Failed to fetch recent messages: {e}")
        return []


def delete_session_messages(session_id: str) -> int:
    """
    Deletes all messages for a given session from the conversations table.
    Returns the number of deleted rows.
    """
    try:
        conn = get_db_connection(connect_db=True)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversations WHERE session_id = %s;",
                (session_id,)
            )
            deleted_count = cur.rowcount
            conn.commit()
        conn.close()
        logger.info(f"Deleted {deleted_count} messages for session '{session_id}'.")
        return deleted_count
    except Exception as e:
        logger.error(f"Failed to delete session messages: {e}")
        raise e


def get_session_summary(session_id: str) -> Optional[str]:
    """
    Returns the latest progressive summary for the given session.
    """
    try:
        conn = get_db_connection(connect_db=True)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT summary FROM conversations WHERE session_id = %s AND summary IS NOT NULL LIMIT 1;",
                (session_id,)
            )
            res = cur.fetchone()
            summary = res[0] if res else None
        conn.close()
        return summary
    except Exception as e:
        logger.error(f"Failed to fetch session summary: {e}")
        return None


def update_session_summary(session_id: str) -> None:
    """
    Checks if message count > 10. If so, takes all messages beyond the most
    recent 10 and updates the running session summary progressively using Gemini.
    """
    try:
        conn = get_db_connection(connect_db=True)
        
        # 1. Get all messages for the session in chronological order
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT role, content FROM conversations WHERE session_id = %s ORDER BY timestamp ASC;",
                (session_id,)
            )
            all_messages = cur.fetchall()
        
        total_count = len(all_messages)
        if total_count <= 10:
            conn.close()
            return  # No summarization needed yet

        # 2. Get messages beyond the last 10 (older messages to be summarized)
        to_summarize = all_messages[:-10]
        
        # 3. Retrieve current summary if any
        current_summary = get_session_summary(session_id)

        # 4. Call Gemini to create/update summary
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("No Gemini API Key available. Skipping progressive summarization.")
            conn.close()
            return
            
        active_key = api_key.split(",")[0].strip()
        genai.configure(api_key=active_key)
        
        # Format the context messages to be summarized
        formatted_messages = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in to_summarize])
        
        prompt = f"""You are a specialized legal assistant summarizer.
Your task is to summarize the early part of a legal discussion between a lawyer and an AI.
Maintain all critical facts, case names, section numbers, contract clauses, and lawyer preferences.

"""
        if current_summary:
            prompt += f"Existing Summary of older conversation:\n{current_summary}\n\n"
            prompt += f"New messages to integrate into the summary:\n{formatted_messages}\n\n"
            prompt += "Please provide an updated, unified, concise running summary incorporating these new messages."
        else:
            prompt += f"Conversation portion to summarize:\n{formatted_messages}\n\n"
            prompt += "Please provide a concise legal summary keeping all key facts, case references, and lawyer preferences."

        model = genai.GenerativeModel(CHAT_MODEL)
        response = model.generate_content(prompt)
        new_summary = response.text.strip()

        # 5. Update summary on all rows for this session_id (updates in place)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET summary = %s WHERE session_id = %s;",
                (new_summary, session_id)
            )
            conn.commit()
        conn.close()
        logger.info(f"Progressive summary updated successfully for session '{session_id}'.")
    except Exception as e:
        logger.error(f"Failed to update session summary: {e}")


# =====================================================================
# LONG-TERM MEMORY FUNCTIONS (MEM0)
# =====================================================================

def add_long_term_memory(user_id: str, lawyer_message: str, ai_response: str, case_ref: Optional[str] = None) -> None:
    """
    Extracts facts from the message exchange, filters duplicates, and saves
    to PostgreSQL pgvector using Mem0.
    """
    try:
        mem = get_mem0_client()
        messages = [
            {"role": "user", "content": lawyer_message},
            {"role": "assistant", "content": ai_response}
        ]
        
        metadata = {}
        if case_ref:
            metadata["case_ref"] = case_ref
        
        # Mem0 determines the category and extracts facts automatically
        mem.add(
            messages=messages,
            user_id=user_id,
            metadata=metadata
        )
        logger.info(f"Mem0 successfully updated long-term memory for user '{user_id}'.")
    except Exception as e:
        logger.error(f"Failed to add memory via Mem0: {e}")


def search_long_term_memory(user_id: str, query: str, case_ref: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Searches the long-term memory database for facts relevant to the query, filtered by user_id and optionally case_ref.
    """
    try:
        mem = get_mem0_client()
        filters = {"user_id": user_id}
        if case_ref:
            filters["case_ref"] = case_ref
            
        response = mem.search(
            query=query,
            filters=filters,
            limit=limit
        )
        if isinstance(response, dict):
            return response.get("results", [])
        return response

    except Exception as e:
        logger.error(f"Failed to search memory via Mem0: {e}")
        return []


def format_facts(relevant_facts: List[Dict[str, Any]]) -> str:
    """
    Formats the search results into a clean bulleted string.
    """
    if not relevant_facts:
        return "- No prior context available."
    
    facts = []
    for fact in relevant_facts:
        memory_text = fact.get("memory") or fact.get("content")
        if not memory_text and "payload" in fact:
            memory_text = fact["payload"].get("data")
        
        if memory_text:
            # Clean up the output formatting
            facts.append(f"- {memory_text}")
            
    return "\n".join(facts) if facts else "- No prior context available."


# =====================================================================
# FULL PROMPT ASSEMBLY
# =====================================================================

def assemble_prompt(user_id: str, session_id: str, case_ref: Optional[str], current_message: str) -> str:
    """
    Gathers long-term memories, session summaries, recent conversation logs,
    and returns a fully structured prompt ready for LLM consumption.
    """
    # 1. Fetch relevant long term memory facts (top 5 facts)
    ltm_results = search_long_term_memory(user_id, current_message, case_ref=case_ref, limit=5)
    formatted_ltm = format_facts(ltm_results)

    # 2. Fetch session summary
    session_summary = get_session_summary(session_id) or "No summary of earlier conversation available."

    # 3. Fetch last 10 messages (short term memory)
    last_10 = get_recent_messages(session_id, limit=10)
    
    formatted_recent = ""
    if last_10:
        formatted_recent = "\n".join([f"{'Lawyer' if m['role'] == 'human' else 'AI'}: {m['content']}" for m in last_10])
    else:
        formatted_recent = "No recent messages."

    # 4. Assemble in the exact prompt structure requested
    prompt = f"""You are an expert legal assistant.
Be concise and formal.
Always cite sources when making legal claims.
Never fabricate case names or statutes.

WHAT YOU KNOW ABOUT THIS LAWYER AND CASE:
{formatted_ltm}

SUMMARY OF EARLIER IN THIS CONVERSATION:
{session_summary}

RECENT CONVERSATION:
{formatted_recent}

LAWYER NOW ASKS:
{current_message}
"""
    return prompt
