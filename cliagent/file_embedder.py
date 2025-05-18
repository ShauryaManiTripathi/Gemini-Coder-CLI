import os
import hashlib
from typing import Dict, List, Optional
import logging
from .vector_store import vector_store

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# File extension to type mapping
FILE_TYPE_MAPPING = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.html': 'html',
    '.css': 'css',
    '.md': 'markdown',
    '.txt': 'text',
    '.json': 'json',
    '.yml': 'yaml',
    '.yaml': 'yaml',
    '.sh': 'shell',
    '.bash': 'shell',
    '.go': 'go',
    '.rs': 'rust',
    '.c': 'c',
    '.cpp': 'cpp',
    '.h': 'c_header',
    '.hpp': 'cpp_header',
    '.java': 'java',
    '.kt': 'kotlin',
    '.swift': 'swift',
    '.rb': 'ruby',
    '.php': 'php',
    '.cs': 'csharp',
    '.jsx': 'jsx',
    '.tsx': 'tsx',
    '.vue': 'vue',
    '.sql': 'sql',
    '.r': 'r',
    '.scala': 'scala',
    '.dart': 'dart',
    '.lua': 'lua',
}

def get_file_type(file_path: str) -> str:
    """Determine the file type based on extension"""
    _, ext = os.path.splitext(file_path.lower())
    return FILE_TYPE_MAPPING.get(ext, 'unknown')

def add_file_to_vector_store(file_path: str, content: str) -> bool:
    """Add a file to the vector store"""
    try:
        if vector_store is None:
            logger.warning("Vector store not initialized, skipping embedding generation")
            return False
        
        file_type = get_file_type(file_path)
        success = vector_store.store_file(file_path, content, file_type)
        
        # Log the current embedding dimension for debug purposes
        if hasattr(vector_store, 'embedding_dim'):
            logger.debug(f"Current embedding dimension: {vector_store.embedding_dim}")
            
        return success
    except Exception as e:
        logger.error(f"Failed to add file to vector store: {e}")
        return False

def remove_file_from_vector_store(file_path: str) -> bool:
    """Remove a file from the vector store"""
    try:
        if vector_store is None:
            logger.warning("Vector store not initialized, skipping embedding removal")
            return False
        
        return vector_store.remove_file(file_path)
    except Exception as e:
        logger.error(f"Failed to remove file from vector store: {e}")
        return False

def find_relevant_files(query: str, limit: int = 3) -> List[Dict[str, str]]:
    """Find files relevant to the query"""
    try:
        if vector_store is None:
            logger.warning("Vector store not initialized, skipping similarity search")
            return []
        
        similar_files = vector_store.find_similar_files(query, limit)
        
        # Format results
        results = []
        for file_path, similarity, preview in similar_files:
            if similarity > 0.7:  # Only include reasonably similar files
                results.append({
                    'file_path': file_path,
                    'similarity': f"{similarity:.2f}",
                    'preview': preview[:200] + "..." if len(preview) > 200 else preview
                })
        
        return results
    except Exception as e:
        logger.error(f"Failed to find relevant files: {e}")
        return []

def read_file_content(file_path: str) -> Optional[str]:
    """Read file content safely"""
    try:
        if not os.path.exists(file_path):
            return None
            
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return None

def process_directory(directory: str) -> int:
    """Process all files in a directory and add them to the vector store"""
    count = 0
    try:
        for root, dirs, files in os.walk(directory):
            for file in files:
                # Skip very large files or hidden files
                file_path = os.path.join(root, file)
                if os.path.getsize(file_path) > 1000000:  # Skip files > 1MB
                    continue
                if file.startswith('.'):
                    continue
                    
                # Skip certain directories
                if any(p.startswith('.') for p in file_path.split(os.path.sep)):
                    continue
                
                content = read_file_content(file_path)
                if content:
                    if add_file_to_vector_store(file_path, content):
                        count += 1
    except Exception as e:
        logger.error(f"Error processing directory {directory}: {e}")
    
    return count
