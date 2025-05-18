# Simple runner script to start the CLI Agent
import sys
import os
from rich.console import Console
import traceback

console = Console()
def check_requirements():
    """Check if all necessary packages are installed"""
    try:
        import google.generativeai
        import rich
        import dotenv
        return True
    except ImportError as e:
        console.print(f"[bold red]Missing dependency:[/bold red] {e}")
        console.print("[yellow]Please install required packages:[/yellow]")
        console.print("pip install -r requirements.txt")
        return False

if __name__ == "__main__":
    try:
        if not check_requirements():
            sys.exit(1)
            
        # Store the original directory
        original_dir = os.getcwd()
        
        console.print("[bold cyan]Starting Gemini CLI Agent...[/bold cyan]")
        
        # Pre-import UI manager to ensure it's initialized before main
        try:
            from cliagent.ui_manager import console as ui_console, display_welcome_screen
            # Display welcome screen here before starting main
            display_welcome_screen()
        except ImportError as e:
            console.print(f"[yellow]Note: Enhanced UI not available: {e}[/yellow]")
        
        # Import main module only after requirements check
        try:
            from cliagent.main import main
            main()
        except ImportError as e:
            console.print(f"[bold red]Error importing main module:[/bold red] {str(e)}")
            console.print("[yellow]Please check your installation.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Fatal error:[/bold red] {str(e)}")
        # Print more details about the error for debugging
        console.print("[bold yellow]Traceback:[/bold yellow]")
        traceback.print_exc()
        
        # Import cleanup directly for emergency cleanup
        try:
            from cliagent.process_manager import cleanup_running_processes
            cleanup_running_processes()
        except Exception:
            pass
        
        # Restore original directory
        try:
            os.chdir(original_dir)
        except:
            pass
