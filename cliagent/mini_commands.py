"""
Mini-commands for CLI Agent that bypass the chat cycle.
These are prefixed with backslash and provide direct actions.
"""

import os
import subprocess
import time
import logging
import glob
from typing import List, Dict, Any, Tuple
from rich.console import Console
from rich.table import Table

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import rich for better output
try:
    from rich.console import Console
    from rich.table import Table
    from rich.syntax import Syntax
    console = Console()
    has_rich = True
except ImportError:
    has_rich = False
    console = None

# Try to import vector functionality
try:
    from .file_embedder import add_file_to_vector_store, get_file_type
    from .vector_store import vector_store
    has_vector_store = True
except ImportError:
    has_vector_store = False
    logger.warning("Vector store functionality not available")

# Import the sticky files tracker
try:
    from .sticky_files import sticky_files_tracker
    has_sticky_files = True
except ImportError:
    has_sticky_files = False
    logger.warning("Sticky files functionality not available")

def handle_shell_command(command: str, current_dir: str) -> str:
    """Directly run a shell command and return the result"""
    try:
        logger.info(f"Running direct shell command: {command} in {current_dir}")
        result = subprocess.run(
            command, 
            shell=True, 
            cwd=current_dir,
            text=True, 
            capture_output=True
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\nErrors:\n{result.stderr}"
            
        return f"Executed: {command}\nExit code: {result.returncode}\n\n{output}"
    except Exception as e:
        return f"Error executing command: {str(e)}"

def handle_vector_update(recursive: bool, current_dir: str) -> str:
    """Update vector store with files in current directory"""
    if not has_vector_store:
        return "Error: Vector store functionality not available"
    
    try:
        start_time = time.time()
        processed_files = 0
        skipped_files = 0
        failed_files = 0
        skipped_dirs = 0
        skipped_images = 0  # Counter for skipped image files
        
        # Define directories to skip during recursive traversal
        skip_dirs = [
            # Python related
            '.venv', 'venv', '__pycache__', '.pytest_cache', '.pyc', 'eggs', '.eggs',
            # JavaScript/Node related
            'node_modules', 'bower_components', '.npm', '.next', 'dist', 'build',
            # Java/Build related
            'target', '.gradle', '.m2', '.ivy2', 'out', 'bin', 'obj',
            # Version control
            '.git', '.svn', '.hg',
            # IDE/Editor related
            '.idea', '.vscode', '.vs',
            # Other common large directories
            'vendor', 'tmp', 'temp', 'log', 'logs'
        ]
        
        # Define image file extensions to skip
        skip_extensions = [
            '.jpg', '.jpeg', '.png', '.svg', '.gif', '.bmp', '.tiff', 
            '.ico', '.webp', '.heic', '.avif', '.eps'
        ]
        
        # Log the current directory for debugging
        logger.info(f"Vector update in directory: {current_dir} (recursive={recursive})")
        
        # Define helper to process a single file
        def process_file(file_path: str) -> bool:
            try:
                # Get absolute path for consistent storage
                abs_path = os.path.abspath(file_path)
                
                # Skip files with image extensions
                _, file_ext = os.path.splitext(abs_path.lower())
                if file_ext in skip_extensions:
                    logger.info(f"Skipping image file: {abs_path}")
                    nonlocal skipped_images
                    skipped_images += 1
                    return False
                
                # Skip very large files
                if os.path.getsize(abs_path) > 1000000:  # Skip files > 1MB
                    logger.info(f"Skipping large file: {abs_path}")
                    return False
                    
                # Skip binary files or files we can't read
                try:
                    with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception as e:
                    logger.info(f"Skipping unreadable file: {abs_path} - {str(e)}")
                    return False
                    
                # Get file type and add to vector store
                file_type = get_file_type(abs_path)
                logger.debug(f"Adding to vector store: {abs_path} (type: {file_type})")
                return add_file_to_vector_store(abs_path, content)
            except Exception as e:
                logger.error(f"Error processing file {file_path}: {e}")
                return False
        
        # Walk directory or just process current directory
        if recursive:
            for root, dirs, files in os.walk(current_dir):
                # Filter out directories to skip (modify dirs in-place to prevent os.walk from descending into them)
                for skip_dir in skip_dirs:
                    dirs_to_remove = [d for d in dirs if d == skip_dir]
                    for d in dirs_to_remove:
                        logger.info(f"Skipping directory: {os.path.join(root, d)}")
                        skipped_dirs += 1
                        dirs.remove(d)
                
                # Skip hidden directories as before
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                
                for file in files:
                    # Skip hidden files
                    if file.startswith('.'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    if process_file(file_path):
                        processed_files += 1
                    else:
                        skipped_files += 1
        else:
            # Just process files in current directory
            for item in os.listdir(current_dir):
                if item.startswith('.'):
                    continue
                    
                file_path = os.path.join(current_dir, item)
                if not os.path.isfile(file_path):
                    continue
                    
                if process_file(file_path):
                    processed_files += 1
                else:
                    skipped_files += 1
        
        elapsed_time = time.time() - start_time
        
        return (f"Vector store update complete in {elapsed_time:.2f}s:\n"
                f"- Directory: {current_dir}\n"
                f"- Processed: {processed_files} files\n"
                f"- Skipped: {skipped_files} files (hidden/large/binary/unreadable)\n"
                f"- Skipped: {skipped_images} image files (jpg/png/svg/etc)\n"
                f"- Skipped: {skipped_dirs} directories (build/dependency folders)\n"
                f"- Failed: {failed_files} files")
                
    except Exception as e:
        return f"Error updating vector store: {str(e)}"

def handle_vector_list(current_dir: str) -> str:
    """List all files in the vector store"""
    if not has_vector_store:
        return "Error: Vector store functionality not available"
        
    try:
        if not hasattr(vector_store, 'memory_store'):
            return "Error: Vector store doesn't have accessible memory store"
            
        files = vector_store.memory_store
        
        if not files:
            return "Vector store is empty. No files indexed."
        
        # Display results in a rich table if available
        if has_rich and console:
            table = Table(title=f"Vector Store Contents ({len(files)} files)")
            table.add_column("#", style="dim")
            table.add_column("File Path", style="cyan")
            table.add_column("File Type", style="green")
            table.add_column("Last Updated", style="yellow")
            
            # Add rows to the table
            for i, (file_path, data) in enumerate(sorted(files.items()), 1):
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get('last_updated', 0)))
                table.add_row(
                    str(i),
                    file_path,  # Show the full path
                    data.get('file_type', 'unknown'),
                    timestamp
                )
                
            # Print the table but don't include it in the return string
            console.print(table)
            
            # Return a simple confirmation message
            return f"Found {len(files)} files in vector store."
        else:
            # Build the complete text list for non-rich UI
            result = f"Found {len(files)} files in vector store:\n\n"
            for i, (file_path, data) in enumerate(sorted(files.items()), 1):
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(data.get('last_updated', 0)))
                result += f"{i}. {file_path} ({data.get('file_type', 'unknown')}) - {timestamp}\n"
            return result
            
    except Exception as e:
        return f"Error listing vector store: {str(e)}"

def handle_vector_search(query: str, current_dir: str) -> str:
    """Search for files in vector store matching the query"""
    if not has_vector_store:
        return "Error: Vector store functionality not available"
        
    if not query:
        return "Error: Query is required for vector search"
        
    try:
        results = vector_store.find_similar_files(query, limit=10)  # Show top 10 results
        
        if not results:
            return f"No files found matching query: '{query}'"
            
        result = f"Found {len(results)} files matching '{query}':\n\n"
        
        # Display results in a rich table if available
        if has_rich and console:
            table = Table(title=f"Search Results for: {query}")
            table.add_column("File Path", style="cyan")
            table.add_column("Similarity", style="green")
            table.add_column("Preview", style="yellow", no_wrap=False)
            
            for file_path, similarity, preview in results:
                # Format similarity as percentage
                sim_percent = f"{similarity * 100:.1f}%"
                # Truncate preview to reasonable length
                short_preview = preview[:50] + "..." if len(preview) > 50 else preview
                table.add_row(
                    os.path.basename(file_path),  # Just the filename
                    sim_percent,
                    short_preview
                )
                
            console.print(table)
            return f"Found {len(results)} matching files."
        else:
            # Fallback to text format
            for file_path, similarity, preview in results:
                sim_percent = f"{similarity * 100:.1f}%"
                result += f"- {file_path} (Similarity: {sim_percent})\n"
                result += f"  Preview: {preview[:100]}...\n\n"
                
            return result
    except Exception as e:
        return f"Error searching vector store: {str(e)}"

def handle_vector_clear(current_dir: str) -> str:
    """Clear all files from the vector store"""
    if not has_vector_store:
        return "Error: Vector store functionality not available"
        
    try:
        if not hasattr(vector_store, 'memory_store'):
            return "Error: Vector store doesn't have accessible memory store"
            
        file_count = len(vector_store.memory_store)
        vector_store.memory_store.clear()
        return f"Cleared {file_count} files from vector store."
    except Exception as e:
        return f"Error clearing vector store: {str(e)}"

def handle_vector_stats(current_dir: str) -> str:
    """Show statistics about the vector store"""
    if not has_vector_store:
        return "Error: Vector store functionality not available"
        
    try:
        if not hasattr(vector_store, 'memory_store'):
            return "Error: Vector store doesn't have accessible memory store"
            
        files = vector_store.memory_store
        
        if not files:
            return "Vector store is empty. No statistics available."
            
        # Gather statistics
        file_count = len(files)
        file_types = {}
        
        for file_path, data in files.items():
            file_type = data.get('file_type', 'unknown')
            file_types[file_type] = file_types.get(file_type, 0) + 1
        
        # Format the output
        result = f"Vector Store Statistics:\n\n"
        result += f"Total files indexed: {file_count}\n\n"
        result += "File types:\n"
        
        for file_type, count in file_types.items():
            result += f"- {file_type}: {count} files\n"
            
        return result
    except Exception as e:
        return f"Error getting vector store statistics: {str(e)}"

def handle_find_files(pattern: str, current_dir: str) -> str:
    """Find files matching a pattern in the current directory"""
    try:
        if not pattern:
            return "Error: Pattern is required for find command"
            
        # Use glob to find matching files
        matching_files = glob.glob(os.path.join(current_dir, pattern), recursive=True)
        
        if not matching_files:
            return f"No files found matching pattern: '{pattern}'"
            
        result = f"Found {len(matching_files)} files matching '{pattern}':\n\n"
        
        for file_path in sorted(matching_files):
            # Get relative path to current directory
            rel_path = os.path.relpath(file_path, current_dir)
            result += f"- {rel_path}\n"
            
        return result
    except Exception as e:
        return f"Error finding files: {str(e)}"

def handle_clear_screen() -> str:
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')
    return "Screen cleared."

def handle_help_command() -> str:
    """Show help for all mini-commands"""
    result = "Available mini-commands:\n\n"
    
    commands = [
        ("\\sh <command>", "Run a shell command directly"),
        ("\\vector update", "Add files in current directory to vector store"),
        ("\\vector update recursive", "Add files recursively to vector store"),
        ("\\vector list", "List all files in vector store"),
        ("\\vector search <query>", "Search vector store for files matching query"),
        ("\\vector clear", "Clear all files from vector store"),
        ("\\vector stats", "Show statistics about vector store"),
        ("\\find <pattern>", "Find files matching pattern in current directory"),
        ("\\clear", "Clear the terminal screen"),
        ("\\pwd", "Print current working directory"),
        ("\\help", "Show this help message"),
        ("\\sticky add <file>", "Add a file to sticky files (always included in context)"),
        ("\\sticky remove <file>", "Remove a file from sticky files"),
        ("\\sticky list", "List all sticky files"),
        ("\\sticky clear", "Clear all sticky files"),
        ("\\sticky update", "Add files in current directory to sticky files"),
        ("\\sticky update <pattern>", "Add files matching pattern to sticky files"),
        ("\\sticky update recursive", "Add all files recursively to sticky files"),
        ("\\sticky update <pattern> recursive", "Add matching files recursively to sticky files"),
        ("\\sticky auto <on|off>", "Enable or disable automatic sticky file addition"),
    ]
    
    # Display commands in a rich table if available
    if has_rich and console:
        table = Table(title="Mini-Command Reference")
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="green")
        
        for cmd, desc in commands:
            table.add_row(cmd, desc)
            
        console.print(table)
        return "Displayed mini-command reference."
    else:
        # Fallback to text format
        for cmd, desc in commands:
            result += f"{cmd}\n    {desc}\n\n"
            
        return result

def handle_pwd(current_dir: str) -> str:
    """Print current working directory"""
    return f"Current working directory: {current_dir}"

def handle_sticky_add(file_path: str, current_dir: str) -> str:
    """Add a file to sticky files"""
    if not has_sticky_files:
        return "Error: Sticky files functionality not available"
    
    try:
        # Handle relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(current_dir, file_path)
            
        if not os.path.exists(file_path):
            return f"Error: File not found: {file_path}"
            
        # Use the explicit method to bypass auto_add_files check
        if sticky_files_tracker.add_sticky_file_explicit(file_path):
            return f"Added file to sticky files: {file_path}"
        else:
            return f"Failed to add file to sticky files: {file_path}"
    except Exception as e:
        return f"Error adding sticky file: {str(e)}"

def handle_sticky_remove(file_path: str, current_dir: str) -> str:
    """Remove a file from sticky files"""
    if not has_sticky_files:
        return "Error: Sticky files functionality not available"
    
    try:
        # Handle relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(current_dir, file_path)
            
        if sticky_files_tracker.remove_sticky_file(file_path):
            return f"Removed file from sticky files: {file_path}"
        else:
            return f"File not found in sticky files: {file_path}"
    except Exception as e:
        return f"Error removing sticky file: {str(e)}"

def handle_sticky_list(current_dir: str) -> str:
    """List all sticky files"""
    if not has_sticky_files:
        return "Error: Sticky files functionality not available"
    
    try:
        sticky_files = sticky_files_tracker.get_sticky_files()
        
        if not sticky_files:
            return "No sticky files configured."
        
        # Display results in a rich table if available
        if has_rich and console:
            table = Table(title=f"Sticky Files ({len(sticky_files)} files)")
            table.add_column("#", style="dim")
            table.add_column("File Path", style="cyan")
            table.add_column("File Type", style="green")
            table.add_column("Status", style="yellow")
            
            for i, file_path in enumerate(sticky_files, 1):
                # Get file type if possible
                file_type = "unknown"
                if has_vector_store:
                    try:
                        from .file_embedder import get_file_type
                        file_type = get_file_type(file_path)
                    except:
                        pass
                
                # Check if file exists
                status = "Found" if os.path.exists(file_path) else "Missing"
                status_style = "green" if os.path.exists(file_path) else "red"
                
                table.add_row(
                    str(i),
                    file_path,
                    file_type,
                    f"[{status_style}]{status}[/{status_style}]"
                )
                
            console.print(table)
            return f"Listed {len(sticky_files)} sticky files."
        else:
            # Plain text format
            result = f"Sticky Files ({len(sticky_files)}):\n\n"
            for i, file_path in enumerate(sticky_files, 1):
                exists = os.path.exists(file_path)
                status = "Found" if exists else "Missing"
                result += f"{i}. {file_path} ({status})\n"
            return result
    except Exception as e:
        return f"Error listing sticky files: {str(e)}"

def handle_sticky_clear(current_dir: str) -> str:
    """Clear all sticky files"""
    if not has_sticky_files:
        return "Error: Sticky files functionality not available"
    
    try:
        count = sticky_files_tracker.clear_sticky_files()
        return f"Cleared {count} sticky files."
    except Exception as e:
        return f"Error clearing sticky files: {str(e)}"

def handle_sticky_update(pattern: str, recursive: bool, current_dir: str) -> str:
    """Scan directory and add matching files to sticky files"""
    if not has_sticky_files:
        return "Error: Sticky files functionality not available"
    
    try:
        # Empty pattern means use default extensions in the scan_directory method
        added_count = sticky_files_tracker.scan_directory(
            current_dir, 
            pattern=pattern,
            recursive=recursive
        )
        
        pattern_msg = f"matching '{pattern}'" if pattern else "matching common code files"
        mode = "recursively" if recursive else "in current directory"
        return f"Added {added_count} files {mode} {pattern_msg} to sticky files."
    except Exception as e:
        return f"Error updating sticky files: {str(e)}"

def process_mini_command(command: str, current_dir: str) -> Tuple[bool, str]:
    """
    Process special mini-commands starting with backslash.
    
    Returns:
        Tuple[bool, str]: (was_mini_command, result_message)
    """
    # Sticky file commands
    if command.startswith("\\sticky add "):
        file_path = command[12:].strip()
        return True, handle_sticky_add(file_path, current_dir)
        
    elif command.startswith("\\sticky remove "):
        file_path = command[15:].strip()
        return True, handle_sticky_remove(file_path, current_dir)
        
    elif command.strip() == "\\sticky list":
        return True, handle_sticky_list(current_dir)
        
    elif command.strip() == "\\sticky clear":
        return True, handle_sticky_clear(current_dir)
        
    elif command.strip() == "\\sticky update":
        # Pass empty pattern to use defaults
        return True, handle_sticky_update("", False, current_dir)
        
    elif command.strip() == "\\sticky update recursive":
        # Pass empty pattern to use defaults 
        return True, handle_sticky_update("", True, current_dir)
        
    elif command.startswith("\\sticky update ") and " recursive" not in command:
        pattern = command[15:].strip()
        return True, handle_sticky_update(pattern, False, current_dir)
        
    elif command.startswith("\\sticky update ") and " recursive" in command:
        pattern = command[15:].replace(" recursive", "").strip()
        return True, handle_sticky_update(pattern, True, current_dir)
    
    # Vector commands
    elif command.strip() == "\\vector list":
        return True, handle_vector_list(current_dir)
        
    elif command.startswith("\\vector search "):
        query = command[15:].strip()
        return True, handle_vector_search(query, current_dir)
        
    elif command.strip() == "\\vector clear":
        return True, handle_vector_clear(current_dir)
        
    elif command.strip() == "\\vector stats":
        return True, handle_vector_stats(current_dir)
        
    elif command.strip() == "\\vector update":
        return True, handle_vector_update(False, current_dir)
        
    elif command.strip() == "\\vector update recursive":
        return True, handle_vector_update(True, current_dir)
    
    # File and shell commands
    elif command.startswith("\\sh "):
        shell_command = command[4:].strip()
        return True, handle_shell_command(shell_command, current_dir)
        
    elif command.startswith("\\find "):
        pattern = command[6:].strip()  # Fixed: Changed trip() to strip()
        return True, handle_find_files(pattern, current_dir)
    
    # Utility commands
    elif command.strip() == "\\clear":
        return True, handle_clear_screen()
        
    elif command.strip() == "\\help":
        return True, handle_help_command()
        
    elif command.strip() == "\\pwd":
        return True, handle_pwd(current_dir)
        
    # Not a recognized mini-command
    return False, ""
