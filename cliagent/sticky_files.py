"""
Module for managing sticky files - files that are always included in context
regardless of vector search results.
"""

import os
import glob
import json
import logging
from typing import List, Dict, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StickyFilesTracker:
    """
    Class to track files that should always be included in the prompt context.
    """
    def __init__(self):
        self.sticky_files = set()
        self.config_path = os.path.join(os.path.expanduser("~"), ".cliagent_sticky_files.json")
        self.load_sticky_files()
    
    def load_sticky_files(self) -> bool:
        """Load sticky files from config file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    data = json.load(f)
                    # Convert to set for faster lookups, filter out non-existent files
                    self.sticky_files = set(file for file in data.get('sticky_files', []) 
                                         if os.path.exists(file))
                return True
            return False
        except Exception as e:
            logger.error(f"Error loading sticky files: {e}")
            self.sticky_files = set()
            return False
    
    def save_sticky_files(self) -> bool:
        """Save sticky files to config file"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump({
                    'sticky_files': list(self.sticky_files),
                }, f)
            return True
        except Exception as e:
            logger.error(f"Error saving sticky files: {e}")
            return False
    
    def add_sticky_file(self, file_path: str) -> bool:
        """Add a file to the sticky files list"""
        if not os.path.exists(file_path):
            logger.warning(f"File does not exist: {file_path}")
            return False
        
        if os.path.isdir(file_path):
            logger.warning(f"Cannot add directory as sticky file: {file_path}")
            return False
            
        # Get absolute path for consistency
        abs_path = os.path.abspath(file_path)
        self.sticky_files.add(abs_path)
        self.save_sticky_files()
        return True
    
    # For compatibility with existing code
    def add_sticky_file_explicit(self, file_path: str) -> bool:
        """Add a file to sticky files (compatibility method)"""
        return self.add_sticky_file(file_path)
    
    def remove_sticky_file(self, file_path: str) -> bool:
        """Remove a file from the sticky files list"""
        # Get absolute path for consistency
        abs_path = os.path.abspath(file_path)
        if abs_path in self.sticky_files:
            self.sticky_files.remove(abs_path)
            self.save_sticky_files()
            return True
        return False
    
    def clear_sticky_files(self) -> int:
        """Clear all sticky files"""
        count = len(self.sticky_files)
        self.sticky_files.clear()
        self.save_sticky_files()
        return count
    
    def get_sticky_files(self) -> List[str]:
        """Get list of all sticky files"""
        # Filter out any files that no longer exist
        self.sticky_files = set(f for f in self.sticky_files if os.path.exists(f))
        self.save_sticky_files()
        return sorted(self.sticky_files)
    
    def scan_directory(self, directory: str, pattern: str = "*", recursive: bool = False) -> int:
        """
        Scan directory for files matching pattern and add them to sticky files
        
        Args:
            directory: Directory to scan
            pattern: Glob pattern to match files (default: "*")
            recursive: Whether to scan recursively (default: False)
            
        Returns:
            Number of files added
        """
        try:
            added_count = 0
            
            # Common code file extensions to match if no specific pattern
            if not pattern or pattern == "":
                extensions = ['py', 'js', 'ts', 'html', 'css', 'md', 'json', 'yaml', 'yml', 
                             'txt', 'jsx', 'tsx', 'c', 'cpp', 'h', 'hpp', 'java', 'go', 'rs']
                
                # Process each extension individually
                for ext in extensions:
                    added_count += self._scan_with_extension(directory, f"*.{ext}", recursive)
                
                return added_count
            
            # Use provided pattern
            result = self._scan_with_extension(directory, pattern, recursive)
            return result
                    
        except Exception as e:
            logger.error(f"Error scanning directory: {e}")
            return 0
            
    def _scan_with_extension(self, directory: str, pattern: str, recursive: bool) -> int:
        """Helper method to scan for files with a specific extension pattern"""
        added_count = 0
        
        try:
            if recursive:
                # For recursive search, manually walk directory tree
                for root, dirs, files in os.walk(directory):
                    # Skip hidden directories and common large directories
                    dirs[:] = [d for d in dirs if not d.startswith('.') and 
                              d not in ['node_modules', '.git', 'venv', '.venv', 
                                        '__pycache__', 'build', 'dist']]
                    
                    # Match files in current directory
                    for file in files:
                        # Skip hidden files
                        if file.startswith('.'):
                            continue
                            
                        # Check if file matches pattern
                        if self._matches_pattern(file, pattern):
                            file_path = os.path.join(root, file)
                            if self.add_sticky_file(file_path):
                                added_count += 1
                                logger.info(f"Added sticky file: {file_path}")
            else:
                # Non-recursive search
                for item in os.listdir(directory):
                    if item.startswith('.'):
                        continue
                        
                    file_path = os.path.join(directory, item)
                    if not os.path.isfile(file_path):
                        continue
                        
                    # Check if file matches pattern
                    if self._matches_pattern(item, pattern):
                        if self.add_sticky_file(file_path):
                            added_count += 1
                            logger.info(f"Added sticky file: {file_path}")
                            
            return added_count
        except Exception as e:
            logger.error(f"Error in _scan_with_extension: {e}")
            return 0
            
    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """Check if filename matches the given pattern"""
        # Simple pattern matching for common glob patterns
        if pattern == "*":
            return True
            
        # Handle *.ext pattern
        if pattern.startswith("*."):
            ext = pattern[2:]
            return filename.endswith(f".{ext}")
            
        # Regular glob matching
        import fnmatch
        return fnmatch.fnmatch(filename, pattern)
    
    # For compatibility with existing code
    def mark_explicit_request(self, is_explicit=True):
        """No-op compatibility method - all requests are now treated equally"""
        pass

# Create a global singleton instance
sticky_files_tracker = StickyFilesTracker()
