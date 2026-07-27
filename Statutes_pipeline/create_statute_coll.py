import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

# Add parent directory (LawMind/) to sys.path to import config.py
sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import STATUTES_COLLECTION, VECTOR_SIZE

COLLECTION_NAME = STATUTES_COLLECTION

# .env is in parent folder (LawMind/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# connect to Qdrant Cloud
client = QdrantClient(
    url=os.getenv("QDRANT_URL"),
    api_key=os.getenv("QDRANT_API_KEY"),
    cloud_inference=True,
    timeout=60
)

# Step 1: Test connection
try:
    collections = client.get_collections()
    print("✅ Connection successful!")
    print(f"Existing collections: {collections}")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    exit()

# Step 2: Create collection with Gemini embedding dimension
client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=VECTOR_SIZE,
        distance=Distance.COSINE
    )
)
print(f"✅ Collection '{COLLECTION_NAME}' created successfully!")

# Verify collection
collection_info = client.get_collection(COLLECTION_NAME)
print(f"Collection info: {collection_info}")