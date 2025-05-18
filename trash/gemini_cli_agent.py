import google.generativeai as genai
import os
import subprocess
import json
import shutil
import pathlib
import time
import re
import threading
import select
import queue
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

# --- Global State ---
# The System Prompt is a detailed instruction set for the LLM.
# It defines its role, capabilities, how to call functions, and context variables.
SYSTEM_PROMPT_TEXT = """
You are Gemini-CLI-Agent, a sophisticated AI assistant that can interact with the user's local command-line environment.

# CONTEXT
- Current Directory: {current_working_directory}
- Directory Structure: Provided in each prompt
- Running Processes: {running_processes_info}

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
   - Args: `path` (required), `content`, `mode` (overwrite/append/insert_line/delete_line_range)

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

# HOW TO RESPOND
You can respond in two ways:

1. For conversation, use plain text.

2. For system actions, use JSON in one of these formats:

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
[
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
]
```

IMPORTANT: For multiple actions, use a flat JSON array, not a nested structure. Each action will be executed in sequence.
"""

running_processes = {}  # {pid: {"process": Popen_obj, "command": str, "output_lines": list, "cid": str_or_None}}
current_working_directory = os.getcwd()

# --- Helper Functions (Utilities/Tools) ---
def get_directory_tree(startpath_str):
    startpath = pathlib.Path(startpath_str)
    tree_str = f"Directory tree for: {startpath.resolve()}\n"
    MAX_DEPTH = 4
    MAX_ITEMS_PER_DIR = 15
    entries_count = 0

    def _get_tree_recursive(current_path, prefix="", current_level=0):
        nonlocal tree_str, entries_count
        if current_level > MAX_DEPTH:
            tree_str += prefix + "└── [Reached Max Depth]\n"
            return

        try:
            # Get all items, sort dirs first, then by name
            paths_iter = current_path.iterdir()
            paths = sorted([p for p in paths_iter if p.is_dir()] + [p for p in paths_iter if p.is_file()], key=lambda p: p.name.lower())
        except PermissionError:
            tree_str += prefix + "└── [Permission Denied]\n"
            return
        except FileNotFoundError:
            tree_str += prefix + "└── [Not Found]\n"
            return

        display_paths = paths
        is_truncated = False
        if len(paths) > MAX_ITEMS_PER_DIR:
            display_paths = paths[:MAX_ITEMS_PER_DIR]
            is_truncated = True

        pointers = ['├── '] * (len(display_paths) -1) + ['└── ']
        if not display_paths: # Empty directory
             if current_level == 0: # If root of listing is empty
                tree_str += "  (Directory is empty)\n"
             return


        for i, path_obj in enumerate(display_paths):
            entries_count += 1
            pointer = pointers[i]
            tree_str += prefix + pointer + path_obj.name + ("/" if path_obj.is_dir() else "") + "\n"
            if path_obj.is_dir():
                if entries_count > 200 : # Overall limit on tree entries
                    if i == len(display_paths) -1 : tree_str += prefix + "    └── [Tree too large, further items omitted]\n"
                    else: tree_str += prefix + "│   └── [Tree too large, further items omitted]\n"
                    continue # Stop adding more branches if tree is huge

                extender = "│   " if pointer == '├── ' else "    "
                _get_tree_recursive(path_obj, prefix + extender, current_level + 1)
        
        if is_truncated:
            tree_str += prefix + ("    " if pointers[-1] == '└── ' else "│   ") + f"... and {len(paths) - MAX_ITEMS_PER_DIR} more items\n"


    _get_tree_recursive(startpath)
    return tree_str.strip()


def update_and_get_running_processes_info():
    global running_processes
    info_str = "Running Processes:\n"
    if not running_processes:
        info_str += "  None\n"
        return info_str.strip()

    completed_pids = []
    has_input_waiting = False
    
    for pid, data in running_processes.items():
        process = data["process"]
        
        # Use the dedicated update function - now non-blocking
        update_specific_process_output(pid)

        status = process.poll()
        cid_info = f"(CID: {data['cid']})" if data['cid'] else ""
        runtime = time.time() - data.get("start_time", time.time())
        runtime_str = f"[Running for {int(runtime)}s]"
        
        if status is None:
            if data.get("expecting_input", False):
                info_str += f"  - PID: {pid} {cid_info} {runtime_str} (WAITING FOR INPUT): {data['command']}\n"
                has_input_waiting = True
            else:
                info_str += f"  - PID: {pid} {cid_info} {runtime_str} (Running): {data['command']}\n"
        else:
            exit_code = data.get("exit_code", status)
            info_str += f"  - PID: {pid} {cid_info} (Completed, exit code {exit_code}): {data['command']}\n"
            completed_pids.append(pid)
        
        # Only show output if we have some
        if data["output_lines"]:
            for line in data["output_lines"]:
                info_str += f"    {line}\n"
        elif status is None:
            info_str += "    (No output captured yet)\n"

    # Add a hint for input if any process is waiting
    if has_input_waiting:
        info_str += "\n  HINT: One or more processes appear to be waiting for input. Use send_input_to_process function.\n"

    # Clean up completed processes - but only if they've been completed for a while
    # This ensures their final output and status remain visible for a time
    current_time = time.time()
    for pid in completed_pids:
        if pid in running_processes:
            data = running_processes[pid]
            # Only remove if process has been completed for at least 60 seconds
            if data.get("completed", False) and current_time - data.get("completion_time", current_time) > 60:
                # Close pipes if they're still open
                try:
                    if not data["process"].stdout.closed: 
                        data["process"].stdout.close()
                except: pass
                try:
                    if not data["process"].stderr.closed:
                        data["process"].stderr.close()
                except: pass
                
                # Remove from tracking
                del running_processes[pid]
            elif not data.get("completion_time"):
                # First time seeing this completed process, mark its completion time
                data["completion_time"] = current_time

    if not running_processes and not completed_pids:
        info_str = "Running Processes:\n  None\n"

    return info_str.strip()

def resolve_path(path_str):
    # Expands user (~), makes path absolute if not already, and joins with CWD if relative
    expanded_path = os.path.expanduser(str(path_str)) # Ensure path_str is string
    if os.path.isabs(expanded_path):
        return os.path.normpath(expanded_path)
    return os.path.normpath(os.path.join(current_working_directory, expanded_path))

# --- Action Handlers ---
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
        os.makedirs(os.path.dirname(path), exist_ok=True) # Ensure parent directory exists
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Success: File '{path}' created."
    except Exception as e:
        return f"Error creating file '{args.get('path') or args.get('file_path')}': {str(e)}"

def handle_update_file(args):
    try:
        path_str = args.get("path")
        path = resolve_path(path_str)
        content = args.get("content", "") # Content might not be needed for delete_line_range
        mode = args.get("mode")

        if not os.path.exists(path) and mode not in ["overwrite", "append"]: # Overwrite/Append can create
             return f"Error: File not found at '{path}' for mode '{mode}'. Only 'overwrite' or 'append' can create if not exists."
        if os.path.isdir(path):
            return f"Error: Path '{path}' is a directory."
        
        # Ensure parent directory exists if creating via overwrite/append
        if mode in ["overwrite", "append"] and not os.path.exists(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path), exist_ok=True)


        if mode == "overwrite":
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Success: File '{path}' overwritten."
        elif mode == "append":
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
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
        return f"Success: File '{path}' deleted."
    except Exception as e:
        return f"Error deleting file '{args.get('path')}': {str(e)}"

def handle_create_folder(args):
    try:
        # Use the normalized path parameter
        path = resolve_path(args.get("path"))
        if not path:
            return "Error: 'path' argument is required for create_folder."
            
        # Debug info to see what path is being used
        print(f"  Debug: Creating folder at path: {path}")
            
        if os.path.exists(path) and not os.path.isdir(path):
            return f"Error: Path '{path}' exists and is a file. Cannot create folder with the same name."
        os.makedirs(path, exist_ok=True) # exist_ok=True means no error if directory already exists
        return f"Success: Folder '{path}' created (or already existed)."
    except Exception as e:
        return f"Error creating folder '{args.get('path')}': {str(e)}"

def handle_delete_folder(args):
    try:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: Folder not found at '{path}'"
        if not os.path.isdir(path):
            return f"Error: Path '{path}' is not a directory."
        if path == os.getcwd() or path == current_working_directory : # Safety check
             return f"Error: Cannot delete the current working directory '{path}'."
        shutil.rmtree(path)
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
    global current_working_directory
    try:
        path_str = args.get("path")
        if not path_str: return "Error: 'path' argument is required for change_directory."

        # Attempt to resolve the new path
        new_path_resolved = resolve_path(path_str)

        if os.path.isdir(new_path_resolved):
            current_working_directory = new_path_resolved
            # os.chdir(current_working_directory) # If you want to change the script's actual CWD too
            return f"Success: Current working directory changed to '{current_working_directory}'."
        else:
            return f"Error: Directory '{new_path_resolved}' (from input '{path_str}') not found or is not a directory."
    except Exception as e:
        return f"Error changing directory to '{args.get('path')}': {str(e)}"


def handle_run_command(args):
    global running_processes
    try:
        command_string = args.get("command_string")
        if not command_string: return "Error: 'command_string' is required for run_command."
        cid = args.get("cid", "")  # Use empty string instead of None for missing CID
        interactive = args.get("interactive", True)  # Default to interactive mode
        
        # Print command being executed for clarity
        print(f"  Executing: {command_string}")
        
        if interactive:
            # Run in foreground interactive mode - let user directly interact
            print("\n--- Starting interactive process - Ctrl+C to return to agent ---")
            try:
                # Use os.system for interactive commands - this will allow direct user interaction
                exit_code = os.system(f"cd {current_working_directory} && {command_string}")
                print(f"\n--- Process completed with exit code: {exit_code} ---")
                return f"Command '{command_string}' completed with exit code {exit_code}"
            except KeyboardInterrupt:
                print("\n--- Interactive process interrupted ---")
                return f"Command '{command_string}' was interrupted by user"
        else:
            # Original background process mode with threading and queue
            process = subprocess.Popen(
                command_string,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=current_working_directory,
                bufsize=1,
                universal_newlines=True
            )
            pid = process.pid
            
            # Create output queue and start background thread for non-blocking reads
            output_queue = queue.Queue()
            output_thread = threading.Thread(
                target=enqueue_output,
                args=(process.stdout, process.stderr, output_queue),
                daemon=True
            )
            output_thread.start()
            
            running_processes[pid] = {
                "process": process,
                "command": command_string,
                "output_lines": [],
                "cid": cid,
                "start_time": time.time(),
                "expecting_input": False,
                "output_queue": output_queue,
                "output_thread": output_thread
            }
            
            # Wait briefly but don't block to collect initial output
            time.sleep(0.2)
            update_specific_process_output(pid)
            
            # Format the response message correctly
            cid_info = f" with CID: '{cid}'" if cid else ""
            return f"Success: Command '{command_string}' started with PID {pid}{cid_info}. Output will be tracked."
    except FileNotFoundError as e:
        return f"Error running command '{args.get("command_string")}': Command not found or path issue. {str(e)}"
    except Exception as e:
        return f"Error running command '{args.get("command_string")}': {str(e)}"

# Add a new function to update the output of a specific process
def update_specific_process_output(pid):
    """Update the output lines for a specific process - non-blocking version"""
    if pid not in running_processes:
        return False
    
    data = running_processes[pid]
    process = data["process"]
    output_queue = data.get("output_queue")
    new_output = False
    
    # Check process status
    status = process.poll()
    if status is not None and pid in running_processes:
        # Process completed, mark for cleanup but don't remove yet
        data["completed"] = True
        data["exit_code"] = status
    
    # Non-blocking read from the queue
    if output_queue:
        try:
            # Get all available output (non-blocking)
            while True:
                try:
                    stream, line = output_queue.get_nowait()
                    if stream == "stdout":
                        for output_line in line.splitlines():
                            if output_line:  # Skip empty lines
                                data["output_lines"].append(f"[STDOUT] {output_line}")
                                new_output = True
                                
                                # Check for common input prompts
                                lower_line = output_line.lower()
                                if any(prompt in lower_line for prompt in ["? ", "y/n", "(y/n)", "select", "choose", "password", "enter", "continue"]):
                                    data["expecting_input"] = True
                    else:  # stderr
                        for output_line in line.splitlines():
                            if output_line:  # Skip empty lines
                                data["output_lines"].append(f"[STDERR] {output_line}")
                                new_output = True
                    
                    output_queue.task_done()
                except queue.Empty:
                    break
        except Exception as e:
            # If queue is broken for some reason, log it
            data["output_lines"].append(f"[ERROR] Error reading output: {str(e)}")
    
    # Trim to keep only last 10 lines
    data["output_lines"] = data["output_lines"][-10:]
    
    return new_output

def handle_send_input_to_process(args):
    try:
        pid_or_cid = args.get("pid_or_cid")
        input_data = args.get("input_data")
        if input_data is None: return "Error: 'input_data' is required for send_input_to_process."

        process_data = find_process_by_pid_or_cid(pid_or_cid)
        if not process_data:
            # If explicit PID/CID not found but we have exactly one waiting process, use that
            waiting_processes = [(pid, data) for pid, data in running_processes.items() 
                                if data.get("expecting_input", False)]
            if len(waiting_processes) == 1:
                pid, process_data = waiting_processes[0]
                print(f"  Note: Using waiting process PID {pid} as default target")
            else:
                # Get a list of available processes for better error messages
                available_processes = []
                for pid, data in running_processes.items():
                    cid_info = f" (CID: {data['cid']})" if data['cid'] else ""
                    waiting_info = " (WAITING FOR INPUT)" if data.get("expecting_input", False) else ""
                    available_processes.append(f"PID {pid}{cid_info}{waiting_info}: {data['command']}")
                
                if available_processes:
                    process_list = "\n    - " + "\n    - ".join(available_processes)
                    return f"Error: Process with PID/CID '{pid_or_cid}' not found. Available processes:{process_list}"
                return f"Error: Process with PID/CID '{pid_or_cid}' not found. No running processes available."

        process = process_data["process"]
        pid = process.pid
        cid = process_data['cid']

        if process.poll() is not None:
            return f"Error: Process PID {pid} (CID: {cid}) has already terminated. Cannot send input."

        print(f"  Sending input to PID {pid} (CID: {cid if cid else 'N/A'}): {input_data}")
        process.stdin.write(input_data)
        
        # Add newline if not present
        if not input_data.endswith("\n"):
            process.stdin.write("\n")
        process.stdin.flush()
        
        # Reset the expecting input flag
        process_data["expecting_input"] = False
        
        # Wait briefly and update the output to capture response - non-blocking now
        time.sleep(0.2)
        update_specific_process_output(pid)
        
        return f"Success: Input sent to process PID {pid} (CID: {cid if cid else 'N/A'})."
    except Exception as e:
        return f"Error sending input to process '{pid_or_cid}': {str(e)}"

def find_process_by_pid_or_cid(pid_or_cid):
    # First check if it's an empty string
    if not pid_or_cid:
        # When no PID/CID specified, try to find a process waiting for input
        waiting_processes = [(pid, data) for pid, data in running_processes.items() 
                             if data.get("expecting_input", False)]
        if len(waiting_processes) == 1:
            return waiting_processes[0][1]  # Return the data of the only waiting process
        return None
        
    # Try to find by PID
    try:
        pid_to_check = int(pid_or_cid)
        if pid_to_check in running_processes:
            return running_processes[pid_to_check]
    except (ValueError, TypeError):
        # Not an integer PID, continue to check CIDs
        pass
    
    # Check by CID (string match)
    if isinstance(pid_or_cid, str):
        for pid, data in running_processes.items():
            if data["cid"] == pid_or_cid:
                return data
                
    # If we reach here with running processes, see if there's only one - in this case
    # we might want to default to it for easier interaction
    if len(running_processes) == 1:
        only_pid = next(iter(running_processes.keys()))
        data = running_processes[only_pid]
        # Only provide default if the process is likely waiting for input
        if data.get("expecting_input", False):
            return data
            
    return None

def handle_kill_process(args):
    global running_processes
    try:
        pid_or_cid = args.get("pid_or_cid")
        process_data = find_process_by_pid_or_cid(pid_or_cid)

        if not process_data:
            return f"Error: Process with PID/CID '{pid_or_cid}' not found or not currently running."

        process = process_data["process"]
        pid = process.pid
        cid = process_data['cid']

        process.terminate() # SIGTERM
        try:
            process.wait(timeout=0.5) # Give it a moment to terminate gracefully
        except subprocess.TimeoutExpired:
            process.kill() # SIGKILL if still running
            try:
                process.wait(timeout=0.5) # Wait for SIGKILL to take effect
            except subprocess.TimeoutExpired:
                 return f"Warning: Process PID {pid} (CID: {cid}) might not have terminated after SIGKILL."
        
        final_status = process.poll()
        # It should be removed by update_and_get_running_processes_info, but clean up if still here
        if pid in running_processes:
            del running_processes[pid]
        return f"Success: Attempted to terminate process PID {pid} (CID: {cid}). Final exit code: {final_status if final_status is not None else 'Unknown (killed)'}."
    except Exception as e:
        return f"Error killing process '{pid_or_cid}': {str(e)}"


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

def extract_json_from_response(text):
    """Extract and normalize JSON actions from model responses with robust error handling"""
    try:
        # Attempt to find JSON within ```json ... ``` markdown block
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if match:
            json_str = match.group(1)
            try:
                json_obj = json.loads(json_str)
                
                # Handle nested formats
                if isinstance(json_obj, dict):
                    # Handle multiple_actions format
                    if json_obj.get("action") == "multiple_actions" and "actions" in json_obj:
                        print("  System: Converting 'multiple_actions' wrapper to array format")
                        actions_array = json_obj.get("actions")
                        if isinstance(actions_array, list):
                            json_obj = actions_array  # Replace with the actual actions array
                    
                    # Handle a common LLM mistake: single-item array wrapped incorrectly
                    elif "action_items" in json_obj and isinstance(json_obj["action_items"], list):
                        print("  System: Converting 'action_items' wrapper to array format")
                        json_obj = json_obj["action_items"]
                    
                    # Handle a common LLM mistake: commands array
                    elif "commands" in json_obj and isinstance(json_obj["commands"], list):
                        print("  System: Converting 'commands' wrapper to array format")
                        json_obj = json_obj["commands"]
                
                # Add debugging for JSON format
                print(f"  System: Extracted JSON type: {type(json_obj).__name__}")
                
                # Handle both single object and array of objects
                if isinstance(json_obj, list):
                    # Process array of actions
                    normalized_actions = []
                    for i, action_item in enumerate(json_obj):
                        if not isinstance(action_item, dict):
                            print(f"  System: Skipping non-dict action item: {action_item}")
                            continue
                        
                        print(f"  System: Processing action {i+1} in array")
                        normalized_action = normalize_action_object(action_item)
                        if normalized_action:
                            normalized_actions.append(normalized_action)
                    
                    return normalized_actions
                elif isinstance(json_obj, dict):
                    # Process single action
                    normalized_action = normalize_action_object(json_obj)
                    if normalized_action:
                        return [normalized_action]  # Return as a list for consistent handling
                    return None
                else:
                    print(f"  System: Extracted JSON is neither dict nor list: {type(json_obj)}")
                    return None
                
            except json.JSONDecodeError as e:
                print(f"  System: Invalid JSON in markdown block: {e}. Content: '{json_str[:100]}...'")
                return None
            except Exception as e:
                print(f"  System: Error processing JSON: {str(e)}")
                return None
        
        # Fallback: if the entire response is just the JSON object
        if text and isinstance(text, str) and text.strip().startswith(("{", "[")):
            try:
                json_obj = json.loads(text.strip())
                
                # Handle both single object and array of objects
                if isinstance(json_obj, list):
                    normalized_actions = []
                    for action_item in json_obj:
                        if not isinstance(action_item, dict):
                            continue
                        
                        normalized_action = normalize_action_object(action_item)
                        if normalized_action:
                            normalized_actions.append(normalized_action)
                    
                    return normalized_actions
                elif isinstance(json_obj, dict):
                    normalized_action = normalize_action_object(json_obj)
                    if normalized_action:
                        return [normalized_action]
                    return None
                else:
                    return None
                    
            except (json.JSONDecodeError, TypeError):
                # Not a valid JSON object
                return None
    except Exception as e:
        print(f"  System: Error in extract_json_from_response: {str(e)}")
        return None
        
    return None

def normalize_action_object(action_obj):
    """Normalize a single action object with comprehensive parameter mappings"""
    if not isinstance(action_obj, dict):
        return None
        
    # Ensure we're working with a dictionary with 'action' key
    if "action" not in action_obj or not isinstance(action_obj["action"], str):
        return None
    
    # Normalize action names
    action_map = {
        "create_directory": "create_folder",
        "mkdir": "create_folder",
        "make_directory": "create_folder",
        "make_folder": "create_folder",
        "make_dir": "create_folder",
        "create_dir": "create_folder",
        
        "delete_directory": "delete_folder",
        "rmdir": "delete_folder",
        "remove_directory": "delete_folder",
        "remove_folder": "delete_folder",
        "rm_dir": "delete_folder",
        "rm_folder": "delete_folder",
        
        "write_file": "create_file",
        "make_file": "create_file",
        
        "remove_file": "delete_file",
        "rm_file": "delete_file",
        "rm": "delete_file",
        
        "cd": "change_directory",
        "chdir": "change_directory",
        
        "ls": "list_directory",
        "dir": "list_directory",
        "list_dir": "list_directory",
        
        "execute": "run_command",
        "exec": "run_command",
        "run": "run_command",
        "shell": "run_command",
        
        "cat": "read_file",
        "view_file": "read_file",
        "open_file": "read_file",
        
        "modify_file": "update_file",
        "edit_file": "update_file",
        
        "input_to_process": "send_input_to_process",
        "process_input": "send_input_to_process",
        "send_to_process": "send_input_to_process",
        
        "terminate_process": "kill_process",
        "stop_process": "kill_process",
        "end_process": "kill_process"
    }
    
    action = action_obj["action"]
    if action in action_map:
        correct_action = action_map[action]
        print(f"  System: Normalized action '{action}' to '{correct_action}'")
        action_obj["action"] = correct_action
    
    # Ensure args exist
    if "args" not in action_obj or not isinstance(action_obj["args"], dict):
        action_obj["args"] = {}
    
    args = action_obj["args"]
    
    # Define parameter mappings for each function
    parameter_mappings = {
        "create_folder": {
            "path": ["path", "dir_path", "directory_path", "folder_path", "dirname", "dir", "folder", "directory"]
        },
        "create_file": {
            "path": ["path", "file_path", "filepath", "filename", "file", "destination", "dest"],
            "content": ["content", "file_content", "text", "data", "source", "code", "body", "contents"]
        },
        "read_file": {
            "path": ["path", "file_path", "filepath", "filename", "file", "source", "src"]
        },
        "update_file": {
            "path": ["path", "file_path", "filepath", "filename", "file", "target"],
            "content": ["content", "file_content", "text", "data", "new_content", "code", "body", "contents"],
            "mode": ["mode", "update_mode", "edit_mode", "method", "operation"],
            "line_number": ["line_number", "line", "line_num", "at_line", "lineno"],
            "start_line": ["start_line", "start", "from_line", "begin_line", "first_line"],
            "end_line": ["end_line", "end", "to_line", "last_line"]
        },
        "delete_file": {
            "path": ["path", "file_path", "filepath", "filename", "file", "target"]
        },
        "delete_folder": {
            "path": ["path", "dir_path", "directory_path", "folder_path", "dirname", "dir", "folder", "directory", "target"]
        },
        "list_directory": {
            "path": ["path", "dir_path", "directory_path", "folder_path", "dirname", "dir", "folder", "directory"]
        },
        "change_directory": {
            "path": ["path", "dir_path", "directory_path", "folder_path", "dirname", "dir", "folder", "directory", "cd_path", "to", "destination"]
        },
        "run_command": {
            "command_string": ["command_string", "command", "cmd", "shell_command", "exec", "execute", "run"],
            "cid": ["cid", "command_id", "id", "identifier"]
        },
        "send_input_to_process": {
            "pid_or_cid": ["pid_or_cid", "pid", "cid", "process_id", "command_id", "id", "identifier", "process"],
            "input_data": ["input_data", "input", "data", "text", "stdin", "command_input"]
        },
        "kill_process": {
            "pid_or_cid": ["pid_or_cid", "pid", "cid", "process_id", "command_id", "id", "identifier", "process"]
        }
    }
    
    # Apply parameter normalization based on action type
    if action_obj["action"] in parameter_mappings:
        # Get the mapping for this specific action
        param_map = parameter_mappings[action_obj["action"]]
        
        # For each canonical parameter name
        for canonical_param, variants in param_map.items():
            # Check if any variant is present in args
            for variant in variants:
                if variant in args and variant != canonical_param and canonical_param not in args:
                    # Found a variant, normalize to canonical name
                    args[canonical_param] = args[variant]
                    print(f"  System: Normalized parameter '{variant}' to '{canonical_param}'")
                    # Don't remove the original to avoid breaking anything that might expect it
    
    # Additional checks for critical parameters
    action_name = action_obj["action"]
    if action_name == "create_folder" and "path" not in args:
        print("  System: Warning - create_folder missing 'path' parameter")
        
    if action_name == "run_command" and "interactive" not in args:
        args["interactive"] = True
    
    return action_obj

# Add these helpers for non-blocking process handling
def non_blocking_read(pipe):
    """Read from a pipe without blocking using select for timeout"""
    if pipe.closed:
        return ""
    
    # Use select to check if there's data available to read without blocking
    r, _, _ = select.select([pipe], [], [], 0)
    if not r:
        return ""  # No data available
        
    return pipe.read(1024)  # Read available data

def enqueue_output(out, err, output_queue):
    """Background thread function to read output without blocking main thread"""
    while True:
        # Try stdout
        stdout_data = non_blocking_read(out)
        if stdout_data:
            output_queue.put(("stdout", stdout_data))
        
        # Try stderr
        stderr_data = non_blocking_read(err)
        if stderr_data:
            output_queue.put(("stderr", stderr_data))
            
        # Check if both pipes are closed
        if out.closed and err.closed:
            break
            
        # Brief sleep to avoid CPU hogging
        time.sleep(0.1)

# Add a cleanup function to ensure proper process termination
def cleanup_running_processes():
    """Properly clean up all running processes"""
    print("\nShutting down running processes...")
    for pid, data in list(running_processes.items()):
        process = data["process"]
        cmd = data["command"]
        print(f"  Terminating PID {pid}: {cmd}")
        
        # Close pipes first if they're open
        try:
            if not process.stdout.closed:
                process.stdout.close()
        except: pass
        try:
            if not process.stderr.closed:
                process.stderr.close()
        except: pass
        
        # Send SIGTERM
        try:
            if process.poll() is None:  # Only if still running
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    # Send SIGKILL if process doesn't terminate
                    process.kill()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        print(f"    Warning: Process {pid} couldn't be killed")
        except Exception as e:
            print(f"    Error terminating process: {e}")

# --- Main Chat Loop ---
def main():
    global current_working_directory # Allow modification by change_directory
    print("\nWelcome to Gemini CLI Agent!")
    print(f"Using Model: {MODEL_NAME}")
    print(f"Initial Working Directory: {current_working_directory}")
    print("Type 'quit' or 'exit' to end session.")
    print("Commands are handled interactively, so you can interact directly with terminal processes.")
    print("Available actions: " + ", ".join(action_handlers.keys()))
    print("----------------------------------------------------")

    # Define safety settings to allow most content generation for this tool's purpose.
    # Adjust these based on your specific needs and Google's API policies.
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
    
    try:
        # Use system_instruction to properly set the system prompt for the model
        model = genai.GenerativeModel(
            MODEL_NAME,
            safety_settings=safety_settings,
            system_instruction="""You are Gemini-CLI-Agent, a powerful AI that can interact with a command-line environment. 
When asked to perform file operations or run commands, you MUST respond using ONLY the specific JSON format.

CORRECT way to run a command:
```json
{
  "action": "run_command",
  "args": {
    "command_string": "npx create-next-app@latest ."
  },
  "cid": "next-install-001"
}
```

NEVER respond with natural language or markdown when executing commands. ONLY use the exact JSON format above.
"""
        )
        # Initialize chat with an empty history
        chat = model.start_chat(history=[])
    except Exception as e:
        print(f"Fatal Error: Could not initialize Gemini Model: {e}")
        print("Please check your API key, internet connection, and model name.")
        return

    action_result_for_next_prompt = "System initialized." # Initial status for the LLM

    try:
        while True:
            # 1. Prepare context for the LLM
            running_procs_info_str = update_and_get_running_processes_info()
            dir_tree_str = get_directory_tree(current_working_directory)

            # Format system prompt with current context 
            current_llm_system_prompt = SYSTEM_PROMPT_TEXT.format(
                current_working_directory=current_working_directory,
                running_processes_info=running_procs_info_str
            )
            
            # Build better prompt for the model to encourage proper function calling
            # Remove this line that uses undefined prompt_prefix
            # final_user_message_for_llm = f"{prompt_prefix}\n"
            
            # Add stronger reminder about function calling syntax for every message
            final_user_message_for_llm = (
                f"[Current Directory: {current_working_directory}]\n"
                f"{dir_tree_str}\n\n"
                f"[Running Processes Info]:\n{running_procs_info_str}\n\n"
            )
            
            if action_result_for_next_prompt:
                final_user_message_for_llm += f"[Previous Action Result]: {action_result_for_next_prompt}\n\n"

            # Add hints if processes are waiting for input
            waiting_for_input = False
            for pid, data in running_processes.items():
                if data.get("expecting_input", False):
                    cid = data.get("cid", "")
                    cid_str = f" (CID: {cid})" if cid else ""
                    final_user_message_for_llm += (
                        f"HINT: Process PID {pid}{cid_str} appears to be waiting for input. "
                        f"Use send_input_to_process! Example:\n```json\n"
                        "{\n"
                        f'  "action": "send_input_to_process",\n'
                        f'  "args": {{\n'
                        f'    "pid_or_cid": "{cid if cid else pid}",\n'
                        f'    "input_data": "y"\n'
                        f'  }}\n'
                        f"}}\n```\n\n"
                    )
                    waiting_for_input = True
                    break
            
            # Get user input here before adding it to the message
            user_input = input(f"\n(cwd: {os.path.basename(current_working_directory) if current_working_directory else 'unknown'}) You: ")
            if user_input.lower() in ['quit', 'exit']:
                print("Exiting agent...")
                break
                
            # If user input is just blank or very short while a process is waiting, hint more strongly
            if waiting_for_input and len(user_input.strip()) <= 1:
                print("\nHINT: A process appears to be waiting for input. You may want to send input to it.")
                
            final_user_message_for_llm += (
                "IMPORTANT: When I ask you to run commands or perform file operations, respond using ONLY the JSON format.\n"
                "For example, to create a Next.js app, respond EXACTLY like this:\n"
                "```json\n"
                "{\n"
                '  "action": "run_command",\n'
                '  "args": {\n'
                '    "command_string": "npx create-next-app@latest ."\n'
                '  },\n'
                '  "cid": "next-installation-001"\n'
                "}\n"
                "```\n\n"
                f"User request: {user_input}\n"
            )

            # 2. Send to Gemini
            try:
                # Send the full message to the model
                response = chat.send_message(final_user_message_for_llm)
                llm_response_text = response.text
                print("\nGemini:", flush=True)

            except Exception as e:
                print(f"  System: Error communicating with Gemini: {e}")
                action_result_for_next_prompt = f"System Error: Gemini API call failed: {e}"
                time.sleep(1) # Prevent rapid error loops if API is down
                continue

            # 3. Process LLM Response: Check for JSON action or treat as text
            try:
                actions = extract_json_from_response(llm_response_text)
                
                if actions and isinstance(actions, list):
                    # Multiple actions to process sequentially
                    all_results = []
                    for i, action_json in enumerate(actions):
                        try:
                            print(f"  Processing action {i+1}/{len(actions)}: {json.dumps(action_json, indent=2)}")
                            
                            action_name = action_json.get("action", "unknown_action")
                            args = action_json.get("args", {})
                            
                            # Ensure args is a dictionary
                            if not isinstance(args, dict):
                                args = {}
                                print("  System: Warning - args is not a dictionary, using empty dict instead")
                            
                            if action_name in action_handlers:
                                try:
                                    # Confirmation step for potentially dangerous actions
                                    dangerous_actions = ["delete_folder", "delete_file"]
                                    if action_name in dangerous_actions:
                                        confirm_prompt = f"  Gemini wants to: {action_name} with args {args}. Execute? (y/N): "
                                        confirmation = input(confirm_prompt).lower()
                                        if confirmation != 'y':
                                            result = f"User cancelled action: {action_name}"
                                            print(f"  System: {result}")
                                            all_results.append(result)
                                            continue
                                    
                                    result = action_handlers[action_name](args)
                                    print(f"  System: {result}")
                                    all_results.append(result)
                                except Exception as e:
                                    error_msg = f"System Error: Exception during execution of action '{action_name}': {str(e)}"
                                    print(f"  System: {error_msg}")
                                    all_results.append(error_msg)
                            else:
                                error_msg = f"System Error: LLM requested unknown action '{action_name}'. No action taken."
                                print(f"  System: {error_msg}")
                                print("  Available actions are: " + ", ".join(action_handlers.keys()))
                                all_results.append(error_msg)
                        
                        except Exception as e:
                            print(f"  System: Error processing action {i+1}: {str(e)}")
                            all_results.append(f"Error processing action: {str(e)}")
                    
                    # Combine results for the next prompt
                    if len(all_results) == 1:
                        action_result_for_next_prompt = all_results[0]
                    else:
                        action_result_for_next_prompt = "Multiple actions processed:\n- " + "\n- ".join(all_results)
                        
                else:
                    # No valid JSON action found, treat as a conversational response
                    print(llm_response_text)
                    # Rest of conversational response handling remains the same
            except Exception as e:
                print(f"  System: Error handling model response: {str(e)}")
                action_result_for_next_prompt = f"Error handling model response: {str(e)}"
            
            # After sending to model and getting response, add a small delay
            # to allow subprocess output processing in background thread
            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nUser interrupted. Exiting agent...")
    finally:
        # Use the improved cleanup function
        cleanup_running_processes()
        print("Gemini CLI Agent terminated.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {str(e)}")
        # Print more details about the error for debugging
        import traceback
        traceback.print_exc()
    finally:
        # Ensure cleanup happens even on unexpected errors
        cleanup_running_processes()
