"""
Shared Config for LegalMind Database Pipeline
===============================================
Import these constants in any script:
    from config import EMBEDDING_MODEL, VECTOR_SIZE, BATCH_SIZE, CHAT_MODEL
"""

import sys
sys.dont_write_bytecode = True  # Prevent creation of __pycache__ folders

# Embedding Config
EMBEDDING_MODEL = "models/gemini-embedding-001"   # Gemini embedding model
VECTOR_SIZE = 768                                  # Target vector size (Gemini output)

# Generative / Chat Model Config
CHAT_MODEL = "gemini-3.1-flash-lite"          # Gemini 3.1 Flash Lite (15 RPM, 500 RPD quota)

# PostgreSQL Configuration Settings
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_DB = "legal_assistant"
POSTGRES_USER = "postgres"
POSTGRES_PASSWORD = "yourpassword"

# Mem0 Configuration Settings
MEM0_LLM_PROVIDER = "gemini"                       # "gemini" or "openai"
MEM0_LLM_MODEL = "gemini-3.1-flash-lite"           # Model for Mem0 LLM fact extraction
MEM0_EMBEDDER_PROVIDER = "gemini"                  # "gemini" or "openai"
MEM0_EMBEDDING_MODEL = "models/gemini-embedding-001"



# Qdrant Collection Names
STATUTES_COLLECTION   = "statutes"                 # Layer 1: Statutory Laws & Acts
PRECEDENTS_COLLECTION = "precedents_db"            # Layer 2: Supreme & High Court Case Laws
MISL_COLLECTION       = "user_misl_db"             # Layer 3: User Uploaded Case Documents (FIRs, etc.)

# Processing Config
BATCH_SIZE = 50             # Batch size for Gemini API & Qdrant upserts
MAX_CHUNK_SIZE = 1500       # Max characters per chunk
MIN_CHUNK_SIZE = 50         # Skip tiny noise chunks
