#!/usr/bin/env python3
"""
Test script to verify the functionality of the vector store implementation.
This script tests the in-memory vector store by:
1. Creating test files
2. Adding files to the vector store
3. Searching for similar content
4. Displaying the results
"""

import os
import sys
import tempfile
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress

# Add the project directory to path if needed
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Initialize console for nice output
console = Console()

def create_test_files():
    """Create temporary test files with different content for testing"""
    console.print("[bold cyan]Creating test files...[/bold cyan]")
    
    # Create a temporary directory for test files
    temp_dir = tempfile.mkdtemp(prefix="vector_test_")
    console.print(f"Using temporary directory: {temp_dir}")
    
    # Create test files with different content
    test_files = {
        "python_code.py": """
def hello_world():
    print("Hello, world!")
    return True

class TestClass:
    def __init__(self):
        self.name = "Test"
        
    def get_name(self):
        return self.name
""",
        "javascript_code.js": """
function calculateSum(a, b) {
    return a + b;
}

const greeting = "Hello, JavaScript!";
console.log(greeting);

// Define a simple class
class Person {
    constructor(name) {
        this.name = name;
    }
    
    sayHello() {
        return `Hello, my name is ${this.name}`;
    }
}
""",
        "readme.md": """
# Vector Store Test

This is a test file for the vector store functionality.

## Features
- In-memory vector storage
- Similarity search
- Embedding generation

The vector store is used to find relevant files based on semantic similarity.
""",
        "requirements.txt": """
numpy>=1.22.0
google-generativeai>=0.3.0
rich>=13.4.2
""",
        "config.ini": """
[general]
debug=true
log_level=INFO

[vector]
model=gemini-embedding-exp-03-07
max_results=5
similarity_threshold=0.7
"""
    }
    
    # Write the test files
    file_paths = {}
    for filename, content in test_files.items():
        file_path = os.path.join(temp_dir, filename)
        with open(file_path, "w") as f:
            f.write(content)
        file_paths[filename] = file_path
    
    console.print(f"[green]Created {len(file_paths)} test files[/green]")
    return file_paths

def test_vector_store(file_paths):
    """Test the vector store functionality"""
    try:
        # Import after ensuring the path is set up
        from cliagent.vector_store import VectorStore
        from cliagent.file_embedder import get_file_type
        
        console.print("\n[bold cyan]Testing Vector Store...[/bold cyan]")
        
        # Create vector store instance
        vector_store = VectorStore()
        console.print("[green]✓[/green] Created vector store instance")
        
        # Add files to the store with progress bar
        with Progress() as progress:
            add_task = progress.add_task("[cyan]Adding files to vector store...", total=len(file_paths))
            
            for filename, file_path in file_paths.items():
                with open(file_path, "r") as f:
                    content = f.read()
                file_type = get_file_type(file_path)
                success = vector_store.store_file(file_path, content, file_type)
                console.print(f"[{'green' if success else 'red'}]{'✓' if success else '✗'}[/{'green' if success else 'red'}] Added {filename} to vector store")
                # Small delay between API calls to avoid rate limits
                time.sleep(0.5)
                progress.update(add_task, advance=1)
        
        # Test queries with progress bar
        test_queries = [
            "Python functions and classes",
            "JavaScript programming and objects",
            "Calculate sum",
            "hello_world",
            "Testclass"
        ]
        
        with Progress() as progress:
            query_task = progress.add_task("[cyan]Running test queries...", total=len(test_queries))
            
            for query in test_queries:
                console.print(f"\n[bold]Testing query:[/bold] {query}")
                # Allow retries for this specific call
                max_attempts = 3
                attempt = 0
                results = None
                
                while attempt < max_attempts:
                    try:
                        results = vector_store.find_similar_files(query, limit=3)
                        break
                    except Exception as e:
                        attempt += 1
                        if attempt < max_attempts:
                            console.print(f"[yellow]Query attempt {attempt} failed. Retrying...[/yellow]")
                            time.sleep(2 * attempt)  # Progressive backoff
                        else:
                            console.print(f"[red]Failed to run query after {max_attempts} attempts[/red]")
                
                if results:
                    # Display results in a table
                    table = Table(title=f"Results for: {query}")
                    table.add_column("File", style="cyan")
                    table.add_column("Similarity", style="green")
                    table.add_column("Preview", style="yellow", no_wrap=False)
                    
                    for file_path, similarity, preview in results:
                        # Get just the filename for cleaner output
                        filename = os.path.basename(file_path)
                        # Truncate preview
                        short_preview = preview[:50] + "..." if len(preview) > 50 else preview
                        # Format similarity as percentage
                        sim_percent = f"{similarity * 100:.1f}%"
                        table.add_row(filename, sim_percent, short_preview)
                    
                    console.print(table)
                else:
                    console.print("[yellow]No results found[/yellow]")
                    
                progress.update(query_task, advance=1)
                # Small delay between API calls
                time.sleep(1)
        
        return True
    except ImportError as e:
        console.print(f"[bold red]Import Error:[/bold red] {str(e)}")
        console.print("Make sure the cliagent package is properly installed")
        return False
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def cleanup(file_paths):
    """Clean up test files"""
    if not file_paths:
        return
        
    console.print("\n[bold cyan]Cleaning up...[/bold cyan]")
    # Get the directory from the first file path
    test_dir = os.path.dirname(next(iter(file_paths.values())))
    try:
        for file_path in file_paths.values():
            if os.path.exists(file_path):
                os.remove(file_path)
                
        # Remove the directory
        if os.path.exists(test_dir):
            os.rmdir(test_dir)
        console.print(f"[green]✓[/green] Removed temporary test directory")
    except Exception as e:
        console.print(f"[yellow]Warning during cleanup: {str(e)}[/yellow]")

def main():
    console.print(Panel.fit("Vector Store Functionality Test", style="bold cyan"))
    
    try:
        # Create test files
        file_paths = create_test_files()
        
        # Test the vector store
        success = test_vector_store(file_paths)
        
        # Clean up test files
        cleanup(file_paths)
        
        # Print final status
        if success:
            console.print(Panel.fit("[bold green]✓ Vector store functionality test passed![/bold green]"))
        else:
            console.print(Panel.fit("[bold red]✗ Vector store functionality test failed[/bold red]"))
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
