import os
import json
import numpy as np
import google.generativeai as genai
import hashlib
from typing import List, Tuple, Optional
from datetime import datetime
import logging
import time
import random
from .config import EMBEDDING_MODEL, EMBEDDING_DIMENSION, MAX_RETRIES, BASE_RETRY_DELAY, MAX_RETRY_DELAY

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, use_in_memory=True):
        """Initialize the vector store - now using in-memory storage by default"""
        try:
            # Always use in-memory mode as requested
            self.in_memory_mode = True
            self.memory_store = {}
            # Start with configured dimension but allow auto-detection
            self.embedding_dim = EMBEDDING_DIMENSION
            # Flag to determine if we've automatically detected the dimension
            self.dimension_auto_detected = False
            logger.info(f"Vector store initialized in memory mode (expected dimension: {self.embedding_dim})")
        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            # Ensure we have a place to store data even if initialization fails
            self.memory_store = {}
            self.embedding_dim = EMBEDDING_DIMENSION

    def get_embedding(self, text: str) -> List[float]:
        """Generate embeddings using Google's embedding model with retry mechanism"""
        retry_count = 0
        
        while True:
            try:
                embedding = genai.embed_content(
                    model=EMBEDDING_MODEL,
                    content=text,
                    task_type="retrieval_document",
                )
                result = embedding["embedding"]
                
                # Auto-detect dimension from first successful embedding
                if not self.dimension_auto_detected:
                    actual_dim = len(result)
                    if actual_dim != self.embedding_dim:
                        logger.info(f"Auto-detecting embedding dimension: {actual_dim} (was configured as {self.embedding_dim})")
                        self.embedding_dim = actual_dim
                    self.dimension_auto_detected = True
                
                # Standardize dimension to the detected size (usually won't be needed after auto-detection)
                result = self._standardize_dimension(result, self.embedding_dim)
                return result
                
            except Exception as e:
                error_str = str(e)
                quota_exceeded = "429 Resource has been exhausted" in error_str or "quota" in error_str.lower()
                
                retry_count += 1
                if quota_exceeded and retry_count <= MAX_RETRIES:
                    # Calculate exponential backoff delay with jitter
                    delay = min(MAX_RETRY_DELAY, (2 ** retry_count) * BASE_RETRY_DELAY + random.uniform(0, 1))
                    logger.warning(f"API quota exceeded ({retry_count}/{MAX_RETRIES}). Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                    continue
                elif retry_count > MAX_RETRIES:
                    logger.error(f"Failed to generate embedding after {MAX_RETRIES} retries")
                    break
                else:
                    logger.error(f"Failed to generate embedding: {e}")
                    break
                
        # Return a zero vector with the standard dimension if we can't get an embedding
        return [0.0] * self.embedding_dim

    def _standardize_dimension(self, vector: List[float], target_dim: int) -> List[float]:
        """Ensure vector has the target dimension by truncating or padding"""
        current_dim = len(vector)
        
        # If dimensions match, return as is
        if current_dim == target_dim:
            return vector
            
        # If dimensions don't match, log a warning
        logger.warning(f"Embedding dimension mismatch: got {current_dim}, expected {target_dim}")
        
        if current_dim > target_dim:
            # Truncate the vector if it's too long
            return vector[:target_dim]
        else:
            # Pad with zeros if it's too short
            return vector + [0.0] * (target_dim - current_dim)

    def store_file(self, file_path: str, content: str, file_type: str) -> bool:
        """Store file content and its embedding in memory"""
        try:
            # Get absolute path for consistency
            abs_path = os.path.abspath(file_path)
            
            # Calculate simple hash of content
            content_hash = hashlib.md5(content.encode()).hexdigest()
            
            # Get content preview (first 500 characters)
            content_preview = content[:500] + "..." if len(content) > 500 else content
            
            # Generate embedding with retry logic
            embedding = self.get_embedding(content)
            
            # Ensure the embedding is the standard dimension
            embedding = self._standardize_dimension(embedding, self.embedding_dim)
            
            # Store in memory using absolute path for consistency
            self.memory_store[abs_path] = {
                'content_hash': content_hash,
                'content_preview': content_preview,
                'embedding': embedding,
                'file_type': file_type,
                'last_updated': datetime.now().timestamp()
            }
            return True
                
        except Exception as e:
            logger.error(f"Error in store_file: {e}")
            return False

    def find_similar_files(self, query: str, limit: int = 3) -> List[Tuple[str, float, str]]:
        """Find files similar to the query text using in-memory search"""
        try:
            # Generate embedding for query with retry logic
            query_embedding = self.get_embedding(query)
            
            # In-memory similarity search
            if not self.memory_store:
                return []
            
            results = []
            for file_path, data in self.memory_store.items():
                file_embedding = data['embedding']
                
                # Ensure both embeddings have the standardized dimension
                query_embedding = self._standardize_dimension(query_embedding, self.embedding_dim)
                file_embedding = self._standardize_dimension(file_embedding, self.embedding_dim)
                
                # Calculate cosine similarity
                similarity = self._cosine_similarity(query_embedding, file_embedding)
                results.append((file_path, similarity, data['content_preview']))
            
            # Sort by similarity (highest first)
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]
            
        except Exception as e:
            logger.error(f"Error in find_similar_files: {e}")
            return []
    
    def _cosine_similarity(self, vec1, vec2):
        """Calculate cosine similarity between two vectors"""
        try:
            # Ensure both vectors have the same standardized length
            vec1 = self._standardize_dimension(vec1, self.embedding_dim)
            vec2 = self._standardize_dimension(vec2, self.embedding_dim)
            
            vec1 = np.array(vec1)
            vec2 = np.array(vec2)
            
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
                
            return dot_product / (norm1 * norm2)
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0

    def remove_file(self, file_path: str) -> bool:
        """Remove a file from the vector store"""
        try:
            if file_path in self.memory_store:
                del self.memory_store[file_path]
            return True
        except Exception as e:
            logger.error(f"Error in remove_file: {e}")
            return False

    def get_file_content_preview(self, file_path: str) -> Optional[str]:
        """Get the content preview for a file"""
        try:
            if file_path in self.memory_store:
                return self.memory_store[file_path]['content_preview']
            return None
        except Exception as e:
            logger.error(f"Error in get_file_content_preview: {e}")
            return None

# Initialize global vector store instance
try:
    vector_store = VectorStore()
except Exception as e:
    logger.error(f"Failed to initialize vector store: {e}")
    vector_store = None
