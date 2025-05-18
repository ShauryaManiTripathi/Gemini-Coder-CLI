"""
Module for tracking file modifications and triggering automatic updates
to vector databases and sticky files.
"""

import os
import time
import logging
from typing import Set, Dict, List, Optional, Callable, Any, Union

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import vector store functionality if available
try:
    from .vector_store import vector_store
    has_vector_store = True
except ImportError:
    logger.warning("Vector store not available for automatic updates")
    has_vector_store = False
    vector_store = None

class FileModificationTracker:
    """
    Tracks file modifications and provides utilities to update
    vector store and sticky files automatically.
    """
    def __init__(self):
        self.modified_files: Set[str] = set()
        self.created_files: Set[str] = set()
        self.deleted_files: Set[str] = set()
        self.last_check_time = time.time()
    
    def add_file(self, path: str, action: str = "created", file_type: str = "file") -> None:
        """
        Compatibility method to match the file_tracker API.
        Maps to the appropriate tracking method based on the action.
        
        Args:
            path: The path to the file
            action: One of 'created', 'modified', or 'deleted'
            file_type: Type of file ('file' or 'folder')
        """
        abs_path = os.path.abspath(path)
        
        if action == "created":
            self.track_creation(abs_path)
            logger.debug(f"File tracked as created: {abs_path}")
        elif action == "modified":
            self.track_modification(abs_path)
            logger.debug(f"File tracked as modified: {abs_path}")
        elif action == "deleted":
            self.track_deletion(abs_path)
            logger.debug(f"File tracked as deleted: {abs_path}")
        
    def track_modification(self, file_path: str) -> None:
        """Track a file that has been modified"""
        abs_path = os.path.abspath(file_path)
        self.modified_files.add(abs_path)
        logger.debug(f"Tracking modified file: {abs_path}")
        
    def track_creation(self, file_path: str) -> None:
        """Track a file that has been created"""
        abs_path = os.path.abspath(file_path)
        self.created_files.add(abs_path)
        self.modified_files.add(abs_path)  # Created files are also modified
        logger.debug(f"Tracking created file: {abs_path}")
        
    def track_deletion(self, file_path: str) -> None:
        """Track a file that has been deleted"""
        abs_path = os.path.abspath(file_path)
        self.deleted_files.add(abs_path)
        logger.debug(f"Tracking deleted file: {abs_path}")
        
    def has_changes(self) -> bool:
        """Check if there are any changes tracked"""
        return bool(self.modified_files or self.created_files or self.deleted_files)
        
    def get_changes(self) -> Dict[str, List[str]]:
        """Get all tracked changes"""
        return {
            'modified': list(self.modified_files),
            'created': list(self.created_files),
            'deleted': list(self.deleted_files)
        }
        
    def clear_changes(self) -> None:
        """Clear all tracked changes"""
        self.modified_files.clear()
        self.created_files.clear()
        self.deleted_files.clear()
        self.last_check_time = time.time()
    
    def _add_to_vector_store(self, file_path: str, content: str) -> bool:
        """Add a file to the vector store directly"""
        if not has_vector_store or not vector_store:
            logger.warning(f"Vector store not available, can't add {file_path}")
            return False
            
        try:
            # Determine file type from extension
            _, ext = os.path.splitext(file_path)
            file_type = ext.lower()[1:] if ext else "txt"  # Remove the leading dot
            
            # Store in vector database
            return vector_store.store_file(file_path, content, file_type)
        except Exception as e:
            logger.error(f"Error adding {file_path} to vector store: {e}")
            return False
    
    def _remove_from_vector_store(self, file_path: str) -> bool:
        """Remove a file from the vector store directly"""
        if not has_vector_store or not vector_store:
            logger.warning(f"Vector store not available, can't remove {file_path}")
            return False
            
        try:
            # Remove from vector store
            return vector_store.remove_file(file_path)
        except Exception as e:
            logger.error(f"Error removing {file_path} from vector store: {e}")
            return False
        
    def update_vector_store(self, update_function=None) -> Dict[str, int]:
        """
        Update vector store with tracked changes
        
        Args:
            update_function: Optional function to update a file in vector store
                            Takes file_path and content as arguments
        
        Returns:
            Dict with counts of files updated, removed, and errors
        """
        if not has_vector_store or not vector_store:
            logger.warning("Vector store not available for updates")
            return {'updated': 0, 'removed': 0, 'errors': 0}
            
        updated = 0
        removed = 0
        errors = 0
        
        # Handle modified and created files
        for file_path in self.modified_files:
            if os.path.exists(file_path):
                try:
                    # Read file content
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    # Use provided update function or our internal method
                    success = False
                    if update_function:
                        try:
                            # Pass content directly to avoid needing to read it twice
                            success = update_function(file_path, content=content)
                        except Exception as e:
                            logger.error(f"Error in custom update function for {file_path}: {e}")
                            success = self._add_to_vector_store(file_path, content)
                    else:
                        success = self._add_to_vector_store(file_path, content)
                        
                    if success:
                        updated += 1
                        logger.info(f"Updated in vector store: {file_path}")
                    else:
                        errors += 1
                        logger.error(f"Failed to update {file_path} in vector store")
                except Exception as e:
                    errors += 1
                    logger.error(f"Error updating {file_path} in vector store: {e}")
        
        # Handle deleted files
        for file_path in self.deleted_files:
            try:
                # Use provided function or internal method
                success = False
                if update_function:
                    try:
                        # Assuming update_function has a delete mode
                        success = update_function(file_path, delete=True)
                    except Exception as e:
                        logger.error(f"Error in custom delete function for {file_path}: {e}")
                        success = self._remove_from_vector_store(file_path)
                else:
                    success = self._remove_from_vector_store(file_path)
                    
                if success:
                    removed += 1
                    logger.info(f"Removed from vector store: {file_path}")
                else:
                    errors += 1
                    logger.error(f"Failed to remove {file_path} from vector store")
            except Exception as e:
                errors += 1
                logger.error(f"Error removing {file_path} from vector store: {e}")
                
        return {'updated': updated, 'removed': removed, 'errors': errors}
    
    def update_sticky_files(self, sticky_files_tracker=None) -> Dict[str, int]:
        """
        Update sticky files with tracked changes
        
        Args:
            sticky_files_tracker: StickyFilesTracker instance
        
        Returns:
            Dict with counts of files updated and errors
        """
        if not sticky_files_tracker:
            logger.warning("No sticky files tracker provided")
            return {'updated': 0, 'errors': 0}
            
        # Don't automatically add files to sticky if auto_add_files is disabled
        if not sticky_files_tracker.auto_add_files:
            logger.info("Automatic sticky file updates disabled")
            return {'updated': 0, 'errors': 0}
            
        updated = 0
        errors = 0
        
        # Get current sticky files
        current_sticky_files = set(sticky_files_tracker.get_sticky_files())
        
        # Check if any modified files are in sticky files
        for file_path in self.modified_files:
            if file_path in current_sticky_files and os.path.exists(file_path):
                try:
                    # Re-add the file to refresh its content
                    sticky_files_tracker.add_sticky_file(file_path)
                    updated += 1
                    logger.info(f"Updated sticky file: {file_path}")
                except Exception as e:
                    errors += 1
                    logger.error(f"Error updating sticky file {file_path}: {e}")
        
        # Handle deleted files
        for file_path in self.deleted_files:
            if file_path in current_sticky_files:
                try:
                    sticky_files_tracker.remove_sticky_file(file_path)
                    updated += 1
                    logger.info(f"Removed deleted file from sticky files: {file_path}")
                except Exception as e:
                    errors += 1
                    logger.error(f"Error removing {file_path} from sticky files: {e}")
                    
        return {'updated': updated, 'errors': errors}

# Global instance
file_tracker = FileModificationTracker()
