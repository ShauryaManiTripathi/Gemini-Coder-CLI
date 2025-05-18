import os
import shutil
from .utils import resolve_path
from .config import PGVECTOR_ENABLED

# Try to import file embedding functionality
try:
    from .file_embedder import add_file_to_vector_store, remove_file_from_vector_store
    has_vector_store = True and PGVECTOR_ENABLED
except ImportError:
    has_vector_store = False

# Try to import file tracker, but don't fail if unavailable
try:
    from .ui_manager import file_tracker
    has_file_tracker = True
except ImportError:
    has_file_tracker = False

# Import the file watcher
try:
    from .file_watcher import file_tracker as file_modification_tracker
    from .file_embedder import add_file_to_vector_store, remove_file_from_vector_store
    has_file_watcher = True
except ImportError:
    has_file_watcher = False

def handle_read_file(args):
    try:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: File not found at '{path}'"
        if os.path.isdir(path):
            return f"Error: Path '{path}' is a directory, not a file."
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        max_len = 2000
        if len(content) > max_len:
            return f"File content of '{path}' (truncated to {max_len} chars):\n{content[:max_len]}..."
        return f"File content of '{path}':\n{content}"
    except Exception as e:
        return f"Error reading file '{args.get('path')}': {str(e)}"

def handle_create_file(args):
    try:
        # Always get the latest current_working_directory
        from .config import current_working_directory
        
        path = resolve_path(args.get("path") or args.get("file_path"))  # Support both parameter names
        if not path:
            return "Error: 'path' argument is required for create_file."
            
        # Fix the issue with incorrect filepath
        if path.endswith("/None") or path == "None":
            suggested_path = os.path.join(current_working_directory, "tic_tac_toe.py")
            print(f"Warning: Invalid path '{path}' detected. Using '{suggested_path}' instead.")
            path = suggested_path
            
        # Support both content and file_content parameter names
        content = args.get("content") or args.get("file_content", "")
        
        if os.path.isdir(path):
            return f"Error: Path '{path}' is an existing directory. Cannot create file with the same name."
        
        # Track if file exists before to determine if this is create or modify
        file_existed = os.path.exists(path)
        
        os.makedirs(os.path.dirname(path), exist_ok=True) # Ensure parent directory exists
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Track file creation/modification if tracking is available
        if has_file_tracker:
            file_tracker.add_file(path, "modified" if file_existed else "created", "file")
            
        # Track changes for automatic vector and sticky updates
        if has_file_watcher:
            if file_existed:
                file_modification_tracker.track_modification(path)
            else:
                file_modification_tracker.track_creation(path)
            
        # Add to vector store if enabled
        if has_vector_store:
            add_file_to_vector_store(path, content)
            
        return f"Success: File '{path}' {'modified' if file_existed else 'created'}."
    except Exception as e:
        return f"Error creating file '{args.get('path') or args.get('file_path')}': {str(e)}"

def handle_update_file(args):
    try:
        path_str = args.get("path")
        path = resolve_path(path_str)
        content = args.get("content", "") # Content might not be needed for delete_line_range
        
        # Set default mode to 'overwrite' if not provided
        mode = args.get("mode", "overwrite")
        
        if not os.path.exists(path) and mode not in ["overwrite", "append"]: # Overwrite/Append can create
             return f"Error: File not found at '{path}' for mode '{mode}'. Only 'overwrite' or 'append' can create if not exists."
        if os.path.isdir(path):
            return f"Error: Path '{path}' is a directory."
        
        # Ensure parent directory exists if creating via overwrite/append
        if mode in ["overwrite", "append"] and not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path), exist_ok=True)

        # Add file tracking for all update operations
        file_existed = os.path.exists(path)
        
        if mode == "overwrite":
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            # Track file modification
            if has_file_tracker:
                file_tracker.add_file(path, "modified", "file")
                
            # Track for automatic updates
            if has_file_watcher:
                file_modification_tracker.track_modification(path)
                
            # Update in vector store
            if has_vector_store:
                add_file_to_vector_store(path, content)
            return f"Success: File '{path}' overwritten."
        elif mode == "append":
            # Read existing content first
            existing_content = ""
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    existing_content = f.read()
            
            # Append new content
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            
            # Track file modification
            if has_file_tracker:
                file_tracker.add_file(path, "modified", "file")
                
            # Track for automatic updates
            if has_file_watcher:
                file_modification_tracker.track_modification(path)
            
            # Update in vector store with combined content
            if has_vector_store:
                full_content = existing_content + content
                add_file_to_vector_store(path, full_content)
                
            return f"Success: Content appended to '{path}'."
        elif mode == "insert_line":
            line_number = args.get("line_number")
            if not isinstance(line_number, int) or line_number <= 0:
                return "Error: 'line_number' must be a positive integer for 'insert_line'."
            if not os.path.exists(path): return f"Error: File '{path}' does not exist for 'insert_line'."
            with open(path, "r+", encoding="utf-8") as f:
                lines = f.readlines()
                # Ensure line_number is within bounds (can insert at end)
                if line_number > len(lines) + 1 :
                    return f"Error: 'line_number' {line_number} is out of bounds for file with {len(lines)} lines."
                lines.insert(line_number - 1, content + "\n")
                f.seek(0)
                f.writelines(lines)
                f.truncate()
            # Track file modification
            if has_file_tracker:
                file_tracker.add_file(path, "modified", "file")
                
            # Track for automatic updates
            if has_file_watcher:
                file_modification_tracker.track_modification(path)
                
            return f"Success: Content inserted at line {line_number} in '{path}'."
        elif mode == "delete_line_range":
            start_line = args.get("start_line")
            end_line = args.get("end_line", start_line)
            if not (isinstance(start_line, int) and start_line > 0 and
                    isinstance(end_line, int) and end_line >= start_line):
                return "Error: 'start_line' and 'end_line' must be valid positive integers with end_line >= start_line."
            if not os.path.exists(path): return f"Error: File '{path}' does not exist for 'delete_line_range'."
            with open(path, "r+", encoding="utf-8") as f:
                lines = f.readlines()
                if start_line > len(lines):
                     return f"Error: 'start_line' {start_line} is out of bounds for file with {len(lines)} lines."
                del lines[start_line-1:min(end_line, len(lines))] # Ensure end_line doesn't go out of bounds
                f.seek(0)
                f.writelines(lines)
                f.truncate()
            # Track file modification
            if has_file_tracker:
                file_tracker.add_file(path, "modified", "file")
                
            # Track for automatic updates
            if has_file_watcher:
                file_modification_tracker.track_modification(path)
                
            return f"Success: Lines {start_line}-{end_line} deleted from '{path}'."
        else:
            return f"Error: Invalid update mode '{mode}'. Supported modes are 'overwrite', 'append', 'insert_line', 'delete_line_range'."
    except Exception as e:
        return f"Error updating file '{args.get('path')}': {str(e)}"

def handle_delete_file(args):
    try:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: File not found at '{path}'"
        if os.path.isdir(path):
            return f"Error: Path '{path}' is a directory. Use delete_folder to delete directories."
        
        os.remove(path)
        
        # Track file deletion
        if has_file_tracker:
            file_tracker.remove_file(path)
            
        # Track for automatic updates
        if has_file_watcher:
            file_modification_tracker.track_deletion(path)
        
        # Remove from vector store
        if has_vector_store:
            remove_file_from_vector_store(path)
        
        return f"Success: File '{path}' deleted."
    except Exception as e:
        return f"Error deleting file '{args.get('path')}': {str(e)}"

def handle_create_folder(args):
    try:
        # Always get the latest current_working_directory
        from .config import current_working_directory
        
        # Use the normalized path parameter
        path = resolve_path(args.get("path"))
        if not path:
            return "Error: 'path' argument is required for create_folder."
            
        # Debug info to see what path is being used
        print(f"  Debug: Creating folder at path: {path}")
        print(f"  Debug: Current working directory: {current_working_directory}")
            
        if os.path.exists(path) and not os.path.isdir(path):
            return f"Error: Path '{path}' exists and is a file. Cannot create folder with the same name."
            
        folder_existed = os.path.exists(path)
        os.makedirs(path, exist_ok=True) # exist_ok=True means no error if directory already exists
        
        # Track folder creation
        if has_file_tracker and not folder_existed:
            file_tracker.add_file(path, "created", "folder")
            
        return f"Success: Folder '{path}' created (or already existed)."
    except Exception as e:
        return f"Error creating folder '{args.get('path')}': {str(e)}"

def handle_delete_folder(args):
    try:
        # Always get the latest current_working_directory
        from .config import current_working_directory
        
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: Folder not found at '{path}'"
        if not os.path.isdir(path):
            return f"Error: Path '{path}' is not a directory."
        if path == os.getcwd() or path == current_working_directory : # Safety check
             return f"Error: Cannot delete the current working directory '{path}'."
        
        shutil.rmtree(path)
        
        # Track folder deletion
        if has_file_tracker:
            file_tracker.remove_file(path)
        
        return f"Success: Folder '{path}' and its contents deleted."
    except Exception as e:
        return f"Error deleting folder '{args.get('path')}': {str(e)}"

def handle_list_directory(args):
    try:
        path_str = args.get("path", ".") # Default to current directory if no path specified
        path = resolve_path(path_str)
        if not os.path.isdir(path):
            return f"Error: Path '{path}' is not a directory or does not exist."
        items = os.listdir(path)
        if not items:
            return f"Directory '{path}' is empty."
        # Add a '/' to directory names for clarity
        formatted_items = [name + "/" if os.path.isdir(os.path.join(path, name)) else name for name in items]
        return f"Contents of directory '{path}':\n" + "\n".join(sorted(formatted_items, key=str.lower))
    except Exception as e:
        return f"Error listing directory '{args.get('path', '.')}': {str(e)}"

def handle_change_directory(args):
    try:
        # Always get the latest current_working_directory
        from .config import current_working_directory as cwd
        
        path_str = args.get("path")
        if not path_str: return "Error: 'path' argument is required for change_directory."

        # Attempt to resolve the new path
        new_path_resolved = resolve_path(path_str)

        if os.path.isdir(new_path_resolved):
            # CRITICAL: First normalize the path to ensure consistent formatting
            new_path_resolved = os.path.normpath(new_path_resolved)
            
            # Check if directory exists and is accessible
            try:
                os.listdir(new_path_resolved)  # Test access
            except (PermissionError, FileNotFoundError) as e:
                return f"Error: Cannot access directory '{new_path_resolved}': {str(e)}"
            
            # Update the global variable in config directly through its module
            import sys
            if 'cliagent.config' in sys.modules:
                sys.modules['cliagent.config'].current_working_directory = new_path_resolved
            
            # This is crucial: actually change the process working directory
            os.chdir(new_path_resolved)
            
            # Get the updated value to confirm
            from .config import current_working_directory
            
            # Log the change for debugging
            print(f"  Debug: Changed directory to {current_working_directory}")
            print(f"  Debug: OS current directory: {os.getcwd()}")
            
            return f"Success: Current working directory changed to '{current_working_directory}'."
        else:
            return f"Error: Directory '{new_path_resolved}' (from input '{path_str}') not found or is not a directory."
    except Exception as e:
        return f"Error changing directory to '{args.get('path')}': {str(e)}"
