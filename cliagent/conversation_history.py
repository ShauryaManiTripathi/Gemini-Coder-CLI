"""
Module for tracking conversation history between user and LLM.
"""

from collections import deque
from typing import Dict, List, Deque, Tuple, Optional
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConversationHistory:
    """
    Tracks the conversation history between the user and LLM.
    """
    def __init__(self, max_history: int = 5):
        """
        Initialize the conversation history tracker.
        
        Args:
            max_history: Maximum number of exchanges to keep in history
        """
        self.max_history = max_history
        self.history: Deque[Dict[str, str]] = deque(maxlen=max_history)
        
    def add_user_message(self, message: str, relevant_files: Optional[List[str]] = None) -> None:
        """
        Add a user message to the history.
        
        Args:
            message: The user's message
            relevant_files: Optional list of files relevant to the message
        """
        if not message:
            return
            
        entry = {
            "role": "user", 
            "message": message
        }
        
        # Add file names if provided
        if relevant_files and len(relevant_files) > 0:
            file_names = [os.path.basename(f) for f in relevant_files if isinstance(f, str)]
            if file_names:
                entry["files"] = file_names
                
        self.history.append(entry)
        logger.debug(f"Added user message to history: {message[:50]}...")
    
    def add_llm_message(self, message: str) -> None:
        """
        Add an LLM message to the history.
        
        Args:
            message: The LLM's response
        """
        if not message:
            return
            
        # Trim very long messages
        if len(message) > 3000:
            message = message[:3000] + "... [truncated]"
            
        self.history.append({
            "role": "llm",
            "message": message
        })
        logger.debug(f"Added LLM message to history: {message[:50]}...")
    
    def get_formatted_history(self) -> str:
        """
        Get the conversation history in a readable format for inclusion in prompts.
        
        Returns:
            Formatted conversation history string
        """
        if not self.history:
            return ""
            
        result = "\n[CONVERSATION HISTORY BEGINS]\n"
        
        for entry in self.history:
            role = entry["role"]
            message = entry["message"]
            
            if role == "user":
                result += f"User: {message}"
                
                # Add files information if available
                if "files" in entry and entry["files"]:
                    result += f" [Referenced files: {', '.join(entry['files'])}]"
                    
                result += "\n"
                
            elif role == "llm":
                result += f"LLM: {message}\n"
                
        result += "\n"
        result += "[CONVERSATION HISTORY ENDS]\n"
        return result
        
    def clear(self) -> None:
        """Clear the conversation history."""
        self.history.clear()

# Global instance
import os
from .config import MAX_HISTORY_PRESERVE
conversation_history = ConversationHistory(max_history=MAX_HISTORY_PRESERVE)
