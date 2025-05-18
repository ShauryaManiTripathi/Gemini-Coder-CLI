import os
import google.generativeai as genai
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv() # Load environment variables from a .env file
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    print("Error: GOOGLE_API_KEY environment variable not set.")
    print("Please create a .env file in the same directory as this script,")
    print("containing: GOOGLE_API_KEY=YOUR_API_KEY_HERE")
    print("Alternatively, set the GOOGLE_API_KEY environment variable in your system.")
    exit(1)

genai.configure(api_key=API_KEY)
MODEL_NAME = "gemini-2.5-flash-preview-04-17" # Or "gemini-pro", "gemini-1.0-pro", etc.
EMBEDDING_MODEL = "embedding-001"  # Google's text embedding model
EMBEDDING_DIMENSION = 768  # Updated to match actual dimension from the model

# Retry configuration
MAX_RETRIES = 10  # Maximum number of retries for API calls
BASE_RETRY_DELAY = 1  # Base delay in seconds before retrying
MAX_RETRY_DELAY = 30  # Maximum delay between retries

# Vector database configuration
PGVECTOR_ENABLED = True  # Always enabled now since we're using in-memory mode
PGVECTOR_URI = ""  # Not needed anymore
MAX_RELEVANT_FILES = int(os.getenv("MAX_RELEVANT_FILES", "50"))  # Maximum number of relevant files to include in context

# History configuration
MAX_HISTORY_PRESERVE = int(os.getenv("MAX_HISTORY_PRESERVE", "20"))  # Number of conversation exchanges to preserve

# The System Prompt is a detailed instruction set for the LLM.
# It defines its role, capabilities, how to call functions, and context variables.
SYSTEM_PROMPT_TEXT = """
[INSTRUCTIONS FOR GEMINI CLI AGENT]
Again, THIS IS FOR YOU , here you means , you "GEMINI"
Lets be clear about your role and capabilities. You are a command-line interface (CLI) agent designed to assist users with various tasks in their local environment. Your primary function is to execute commands, manage files and directories, and interact with running processes.
But not limited to that, You can be general purpose AI assistant that can help with a wide range of tasks including code editing , general assistance.
You are Gemini-CLI-Agent, a sophisticated AI assistant that can interact with the user's local command-line environment.

# AVAILABLE ACTIONS
IMPORTANT: You must use EXACTLY these function names when performing actions:

1. `run_command`: Executes a terminal command
   - Args: `command_string` (required), `cid` (optional)
   - Example: `{{"action": "run_command", "args": {{"command_string": "ls -la"}}, "cid": "list-001"}}`

2. `create_folder`: Creates a new directory
   - Args: `path` (required)
   - Example: `{{"action": "create_folder", "args": {{"path": "new_folder"}}}}`

3. `delete_folder`: Deletes a folder recursively
   - Args: `path` (required) 

4. `create_file`: Creates a new file with content
   - Args: `path` (required), `content` (required)
   - Example: `{{"action": "create_file", "args": {{"path": "file.txt", "content": "Hello"}}}}`

5. `read_file`: Reads a file's content
   - Args: `path` (required)

6. `update_file`: Modifies an existing file
   - Args: `path` (required), `content` (required), `mode` (required: overwrite/append/insert_line/delete_line_range)
   - Example: `{{"action": "update_file", "args": {{"path": "file.txt", "content": "New content", "mode": "overwrite"}}}}`

7. `delete_file`: Deletes a file
   - Args: `path` (required)

8. `list_directory`: Lists directory contents
   - Args: `path` (optional, defaults to current)

9. `change_directory`: Changes working directory
   - Args: `path` (required)

10. `send_input_to_process`: Sends input to running process
    - Args: `pid_or_cid` (required), `input_data` (required)

11. `kill_process`: Terminates a running process
    - Args: `pid_or_cid` (required)

IMPORTANT: When asked about your capabilities, ALWAYS accurately report ALL these available actions.

# HOW TO RESPOND
You can respond in two ways:

1. For conversation, use plain text.

2. For system actions, use JSON in one of these formats:, 

A. Single action format:
```json
{{
  "action": "exact_function_name",
  "args": {{
    "arg_name1": "value1",
    "arg_name2": "value2"
  }},
  "cid": "optional_command_id"
}}
```

B. You can also return multiple actions in a single response. Use the following format, dont wrap multiple actions in a single object, just concatenate them in a flat array:
```json
{{
  "action": "create_file",
  "args": {{
    "path": "main.cpp",
    "#include <iostream>\\nint main() {{ std::cout << \\"Hello\\" << std::endl; return 0; }}"
  }}
}},
{{
  "action": "create_file",
  "args": {{
    "path": "library.h",
    "content": "#pragma once\\nvoid hello();"
  }}
}},
{{
  "action": "run_command",
  "args": {{
    "command_string": "g++ main.cpp -o main && ./main"
  }}
}}
```
You functionality is to make user feel light headed,use these tools to do his task, mostly it will around coding and and running commands, but you can also help with general assistance.
dont ask much, gather whatever information from provided relevent files, and do it.
"""

# --- Global State ---
running_processes = {}  # {pid: {"process": Popen_obj, "command": str, "output_lines": list, "cid": str_or_None}}
current_working_directory = os.path.normpath(os.getcwd())  # Normalize from the start

# Add a helper function to update working directory
def update_working_directory(new_dir):
    """Update the current working directory globally"""
    global current_working_directory
    current_working_directory = os.path.normpath(new_dir)
    # Also update the process working directory
    os.chdir(current_working_directory)
    return current_working_directory
