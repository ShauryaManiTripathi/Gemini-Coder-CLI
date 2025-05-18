import os
import time
import shutil
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.table import Table
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.rule import Rule

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.completion import WordCompleter
    has_prompt_toolkit = True
except ImportError:
    has_prompt_toolkit = False

# Initialize console
console = Console()
input_history = InMemoryHistory() if has_prompt_toolkit else None
prompt_session = None

def setup_prompt_session():
    """Initialize the prompt session with common actions as completions"""
    global prompt_session
    if not has_prompt_toolkit:
        return False
        
    try:
        common_actions = [
            "run", "ls", "cd", "cat", "create file", "edit file", "delete file",
            "create folder", "delete folder", "help", "exit", "quit"
        ]
        
        # Add mini-commands to the suggestion list
        mini_commands = [
            # Shell commands
            "\\sh", "\\clear", "\\pwd", "\\help", "\\find",
            
            # Vector store commands
            "\\vector update", "\\vector update recursive", "\\vector list",
            "\\vector search", "\\vector stats", "\\vector clear",
            
            # Sticky files commands
            "\\sticky add", "\\sticky remove", "\\sticky list", "\\sticky clear",
            "\\sticky update", "\\sticky update recursive"
        ]
        
        # Combine common actions and mini-commands
        all_suggestions = common_actions + mini_commands
        completer = WordCompleter(all_suggestions)
        prompt_session = PromptSession(history=input_history, completer=completer)
        return True
    except:
        return False

# File tracking system
class FileTracker:
    def __init__(self):
        self.tracked_files = {}  # path -> {"action": str, "timestamp": float, "type": "file"|"folder"}
        self.max_history = 50  # Maximum number of files to track

    def add_file(self, path, action="created", file_type="file"):
        """Track a file with action (created, modified, deleted)"""
        self.tracked_files[path] = {
            "action": action,
            "timestamp": time.time(),
            "type": file_type
        }
        # Trim if too many entries
        if len(self.tracked_files) > self.max_history:
            # Remove oldest entries
            sorted_items = sorted(self.tracked_files.items(), key=lambda x: x[1]["timestamp"])
            for i in range(len(sorted_items) - self.max_history):
                del self.tracked_files[sorted_items[i][0]]
    
    def remove_file(self, path):
        """Mark a file as deleted or remove it from tracking"""
        if path in self.tracked_files:
            # Mark as deleted but keep in history
            self.tracked_files[path] = {
                "action": "deleted",
                "timestamp": time.time(),
                "type": self.tracked_files[path]["type"]
            }
    
    def has_changes(self):
        """Check if there are any tracked file changes"""
        return len(self.tracked_files) > 0
    
    def display_changes(self):
        """Display tracked file changes"""
        if not self.tracked_files:
            return
            
        console.print(Text("Recent file changes: ", style="bold cyan"), end="")
        console.print(self.get_tracked_files_table())
    
    def get_tracked_files_table(self):
        """Return a rich table of tracked files"""
        if not self.tracked_files:
            return None
            
        # Sort by most recent
        sorted_files = sorted(
            self.tracked_files.items(), 
            key=lambda x: x[1]["timestamp"],
            reverse=True
        )[:5]  # Only show 5 most recent
        
        # Create compact representation as text
        text = Text()
        for path, info in sorted_files:
            file_type = info["type"]
            action = info["action"]
            basename = os.path.basename(path)
            
            if action == "created":
                icon = "📄" if file_type == "file" else "📁"
                style = "green"
            elif action == "modified":
                icon = "📝"
                style = "yellow"
            elif action == "deleted":
                icon = "❌"
                style = "red"
                basename = f"[strike]{basename}[/strike]"
            else:
                icon = "📄" if file_type == "file" else "📁"
                style = "white"
                
            text.append(f"{icon} ", style=style)
            text.append(f"{basename}", style=style)
            text.append(" | ", style="dim")
        
        if text:
            text.append("\n", style="")
            
        return text

# Global file tracker instance
file_tracker = FileTracker()

# Add a class to track relevant context files
class ContextFileTracker:
    """Tracks files used for context in prompts."""
    
    def __init__(self):
        self.relevant_files = []
        self.retry_count = 0
        self.error_message = None
        self.sticky_files = []
    
    def set_relevant_files(self, files, retry_count=0, error_message=None):
        """Set the list of relevant files found from vector search."""
        self.relevant_files = files
        self.retry_count = retry_count
        self.error_message = error_message
    
    def set_sticky_files(self, files):
        """Set the list of sticky files."""
        self.sticky_files = files
    
    def has_files(self):
        """Check if there are any files to display."""
        return len(self.relevant_files) > 0 or len(self.sticky_files) > 0
    
    def display_files(self):
        """Display info about files included in context."""
        if not console:
            return
            
        # Setup title with counts
        sticky_count = len(self.sticky_files)
        vector_count = len(self.relevant_files)
        total_count = sticky_count + vector_count
        
        if total_count == 0:
            return
            
        console.print(f"Context files: {total_count} total ([cyan]{sticky_count} sticky[/cyan], [green]{vector_count} vector[/green])")
        
        # Group files by source
        if self.sticky_files:
            console.print("[cyan]Sticky files:[/cyan]")
            for i, file_info in enumerate(self.sticky_files[:5], 1):
                file_path = file_info.get("file_path", "Unknown")
                console.print(f"  {i}. [cyan]{file_path}[/cyan]")
            
            if len(self.sticky_files) > 5:
                console.print(f"  ... and {len(self.sticky_files) - 5} more sticky files")
        
        if self.relevant_files:
            console.print("[green]Vector DB files:[/green]")
            for i, file_info in enumerate(self.relevant_files[:5], 1):
                file_path = file_info.get("file_path", "Unknown")
                similarity = file_info.get("similarity", 0)
                # Convert similarity to float before formatting
                try:
                    similarity_value = float(similarity)
                    console.print(f"  {i}. [green]{file_path}[/green] ({similarity_value:.2f})")
                except (ValueError, TypeError):
                    # Handle case where similarity isn't a valid float
                    console.print(f"  {i}. [green]{file_path}[/green] ({similarity})")
            
            if len(self.relevant_files) > 5:
                console.print(f"  ... and {len(self.relevant_files) - 5} more vector files")
    
    def get_relevant_files_text(self):
        """Return a formatted text representation of relevant files."""
        if not self.has_files():
            return None
            
        # Create compact representation as text
        text = Text()
        
        # Add sticky files
        for file_info in self.sticky_files[:10]:
            file_path = file_info.get("file_path", "Unknown")
            basename = os.path.basename(file_path)
            text.append("📌 ", style="cyan")
            text.append(f"{basename}", style="cyan")
            text.append(" | ", style="dim")
            
        # Add vector search files
        for file_info in self.relevant_files[:10]:
            file_path = file_info.get("file_path", "Unknown")
            basename = os.path.basename(file_path)
            similarity = file_info.get("similarity", 0)
            
            # Format the similarity based on its type
            text.append("🔍 ", style="green")
            
            # Convert similarity to float if possible, otherwise use as-is
            try:
                similarity_value = float(similarity)
                text.append(f"{basename} ({similarity_value:.2f})", style="green")
            except (ValueError, TypeError):
                # Handle case where similarity isn't a valid float
                text.append(f"{basename} ({similarity})", style="green")
                
            text.append(" | ", style="dim")
            
        # Add ellipsis if there are more files
        total_files = len(self.sticky_files) + len(self.relevant_files)
        shown_files = min(total_files, 6)
        if total_files > shown_files:
            text.append(f"...+{total_files - shown_files} more", style="dim")
            
        return text

# Global context file tracker instance
context_file_tracker = ContextFileTracker()

def get_terminal_size():
    """Get current terminal size"""
    return shutil.get_terminal_size((80, 24))  # Default fallback

def draw_horizontal_divider():
    """Draw a horizontal divider across the terminal width"""
    term_width = get_terminal_size()[0]
    console.print("─" * term_width, style="dim")

def print_header(current_working_directory):
    """Print header with current directory and horizontal divider"""
    # Get terminal width
    term_width = get_terminal_size()[0]
    
    # Create right-aligned file info if files have been tracked
    file_info = file_tracker.get_tracked_files_table()
    
    # Header line with directory and right-aligned file info
    header = Text()
    
    # Add directory info
    current_dir = os.path.basename(current_working_directory)
    parent_dir = os.path.basename(os.path.dirname(current_working_directory))
    if parent_dir:
        path_display = f"{parent_dir}/{current_dir}"
    else:
        path_display = current_dir
        
    header.append("📂 ", style="blue")
    header.append(f"{path_display}", style="bold green")
    
    # Print the header
    console.print(header)
    
    # Add horizontal divider
    draw_horizontal_divider()
    
    # If we have file tracking info, show it with a divider
    if file_info:
        console.print(Text("Recent file changes: ", style="bold cyan"), end="")
        console.print(file_info)
        
    # Show relevant context files if available
    context_files = context_file_tracker.get_relevant_files_text()
    if context_files:
        console.print(Text("Context files: ", style="bold magenta"), end="")
        console.print(context_files)

def print_model_response(text):
    """Print the model's response with syntax highlighting"""
    # For responses with code blocks, use markdown rendering
    if "```" in text:
        console.print(Markdown(text))
    else:
        # For regular text responses, just print them directly
        console.print(text)

def print_footer():
    """Print footer with horizontal line and file tracker info"""
    draw_horizontal_divider()
    
    # Show file tracker information if available
    if file_tracker and file_tracker.has_changes():
        file_tracker.display_changes()
    
    # Show context file tracker information
    if context_file_tracker and context_file_tracker.has_files():
        # Make sure to display context files even when there are no changes
        context_file_tracker.display_files()

# Ensure prompt session is initialized
prompt_session = None
setup_prompt_session()

def get_user_input(current_directory):
    """Get user input with advanced editing capabilities if available"""
    global prompt_session
    
    # Ensure command suggestions are available from the start
    if prompt_session is None and has_prompt_toolkit:
        setup_prompt_session()
        
    dir_name = os.path.basename(current_directory) if current_directory else "unknown"
    prompt = f"(cwd: {dir_name}) You: "
    
    # Show mini-command hint on first interaction (always show once)
    if not hasattr(get_user_input, "shown_mini_command_hint"):
        get_user_input.shown_mini_command_hint = True
        if has_prompt_toolkit and console:
            console.print("[yellow]Available mini-commands: \\help, \\vector, \\sticky, \\sh, \\find[/yellow]")
    
    if has_prompt_toolkit and prompt_session:
        try:
            # Use prompt_toolkit for advanced input handling
            user_input = prompt_session.prompt(prompt)
            return user_input
        except Exception as e:
            console.print(f"[yellow]Input handling error: {e}, falling back to basic input[/yellow]")
            pass
    
    # Regular input as fallback
    return input(prompt)

def display_welcome_screen():
    """Display a welcome screen when the program starts"""
    console.clear()
    
    # Create a nice header
    console.print(Rule("✨ Gemini CLI Agent ✨", style="cyan"))
    
    console.print("\n[bold cyan]Welcome to Gemini CLI Agent![/bold cyan]")
    console.print("A powerful terminal assistant powered by Google's Gemini model.")
    
    console.print("\n[bold yellow]Features:[/bold yellow]")
    console.print("• Execute system commands and interact with processes")
    console.print("• File operations: create, read, update, delete files and directories")
    console.print("• Intelligent assistance through natural language requests")
    console.print("• Track file changes and monitor running processes")
    
    # Add mini-commands section - make this stand out more
    console.print("\n[bold magenta]Mini-Commands (Type these directly):[/bold magenta]")
    
    # Shell commands
    console.print("• [green]\\sh <command>[/green] - Run shell command directly")
    console.print("• [green]\\clear[/green] - Clear the terminal screen")
    console.print("• [green]\\pwd[/green] - Print current working directory")
    console.print("• [green]\\help[/green] - Show all available mini-commands")
    
    # Vector store commands - show most important ones
    console.print("• [green]\\vector update[/green] - Add current directory files to vector index")
    console.print("• [green]\\vector list[/green] - List all files in vector store")
    console.print("• [green]\\vector search <query>[/green] - Search for files matching query")
    
    # Sticky files commands - show most important ones
    console.print("• [green]\\sticky add <file>[/green] - Add file to always include in context")
    console.print("• [green]\\sticky list[/green] - Show all sticky files")
    console.print("• [green]\\sticky update[/green] - Add current directory files to sticky list")
    
    # Add horizontal divider
    console.print(Rule(style="dim cyan"))
    
    console.print("\nType [bold green]'exit'[/bold green] or [bold green]'quit'[/bold green] to end the session.")
    console.print("[bold cyan]Starting agent...[/bold cyan]\n")
