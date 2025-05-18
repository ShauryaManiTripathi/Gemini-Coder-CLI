from .file_operations import (
    handle_read_file, handle_create_file, handle_update_file, handle_delete_file,
    handle_create_folder, handle_delete_folder, handle_list_directory, handle_change_directory
)
from .command_executor import (
    handle_run_command, handle_send_input_to_process, handle_kill_process
)

# Try to import vector functionality
try:
    from .file_embedder import add_file_to_vector_store, get_file_type
    has_vector_store = True
except ImportError:
    has_vector_store = False

# Dictionary mapping action names to their handler functions
action_handlers = {
    "read_file": handle_read_file,
    "create_file": handle_create_file,
    "update_file": handle_update_file,
    "delete_file": handle_delete_file,
    "create_folder": handle_create_folder,
    "delete_folder": handle_delete_folder,
    "list_directory": handle_list_directory,
    "change_directory": handle_change_directory,
    "run_command": handle_run_command,
    "send_input_to_process": handle_send_input_to_process,
    "kill_process": handle_kill_process,
}

def handle_create_file(args):
    """Create a new file with content"""
    try:
        # ...existing code for creating file...
        
        # After successfully creating the file, add it to vector store
        if has_vector_store and os.path.exists(path):
            try:
                file_type = get_file_type(path)
                add_file_to_vector_store(path, content)
                return f"Success: File '{path}' created and added to vector store."
            except Exception as e:
                return f"Success: File '{path}' created. (Vector store update failed: {str(e)})"
                
        return f"Success: File '{path}' created."
    except Exception as e:
        return f"Error creating file '{args.get('path') or args.get('file_path')}': {str(e)}"

def handle_update_file(args):
    """Update an existing file"""
    try:
        # ...existing code for updating file...
        
        # After successfully updating the file, update it in vector store
        if has_vector_store and os.path.exists(path) and mode != "delete_line_range":
            try:
                # For modes with new content, we need to read the updated file
                if mode in ["overwrite", "append", "insert_line"]:
                    with open(path, "r", encoding="utf-8") as f:
                        updated_content = f.read()
                    file_type = get_file_type(path)
                    add_file_to_vector_store(path, updated_content)
                    return f"Success: File '{path}' updated and vector store refreshed."
            except Exception as e:
                return f"Success: File '{path}' updated. (Vector store update failed: {str(e)})"
                
        return f"Success: File '{path}' updated with mode '{mode}'."
    except Exception as e:
        return f"Error updating file '{args.get('path')}': {str(e)}"
