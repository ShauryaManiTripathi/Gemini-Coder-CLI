import os
import json
import time
import signal
import random
import google.generativeai as genai
import google.genai as genaiv2
from google.genai import types
from .config import MODEL_NAME, SYSTEM_PROMPT_TEXT, current_working_directory, running_processes, PGVECTOR_ENABLED, MAX_RELEVANT_FILES, MAX_RETRIES
from .utils import get_directory_tree
from .process_manager import update_and_get_running_processes_info, cleanup_running_processes
from .json_parser import extract_json_from_response
from .actions import action_handlers
import logging
logging.getLogger('google_genai').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)

# Import the conversation history tracker
try:
    from .conversation_history import conversation_history
    has_conversation_history = True
except ImportError:
    has_conversation_history = False
    print("Warning: Conversation history tracking not available")

# Import the mini-command processor
try:
    from .mini_commands import process_mini_command
    has_mini_commands = True
except ImportError:
    has_mini_commands = False

# Try to import vector search functionality
try:
    from .file_embedder import find_relevant_files, read_file_content
    has_vector_search = True and PGVECTOR_ENABLED
except ImportError:
    has_vector_search = False

# Try to import rich UI components, but don't break if missing
try:
    from rich.console import Console
    from rich.syntax import Syntax
    from .ui_manager import (
        console, print_header, print_model_response, file_tracker,
        get_user_input, display_welcome_screen, draw_horizontal_divider,
        print_footer, context_file_tracker
    )
    has_rich_ui = True
except ImportError:
    has_rich_ui = False
    console = None

# Import the sticky files tracker
try:
    from .sticky_files import sticky_files_tracker
    has_sticky_files = True
except ImportError:
    has_sticky_files = False

# Import the file watcher
try:
    from .file_watcher import file_tracker as file_modification_tracker
    has_file_watcher = True
except ImportError:
    has_file_watcher = False

def main():
    # Always access current_working_directory from config to ensure latest value
    from .config import current_working_directory
    
    # Try to display the welcome screen with rich formatting
    # Skip this since we now show it in the runner script before main() is called
    welcome_already_shown = True
    
    # Define safety settings to allow most content generation for this tool's purpose.
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
    
    try:
        # Create a list of available actions for the system instruction
        available_actions_str = ", ".join([f"`{action}`" for action in action_handlers.keys()])
        # Use system_instruction to properly set the system prompt for the model
        model = genai.GenerativeModel(
            MODEL_NAME,
            safety_settings=safety_settings,
            system_instruction=f"""
            Lets be clear about your role and capabilities. You are a command-line interface (CLI) agent designed to assist users with various tasks in their local environment. Your primary function is to execute commands, manage files and directories, and interact with running processes.
But not limited to that, You can be general purpose AI assistant that can help with a wide range of tasks including code editing , general assistance.
            you are a powerful AI that can interact with a command-line environment. 
When asked to perform file operations or run commands, you MUST respond using ONLY the specific JSON format.

AVAILABLE ACTIONS: {available_actions_str}

CORRECT way to run a command:
```json
{{
  "action": "run_command",
  "args": {{
    "command_string": "npx create-next-app@latest ."
  }},
  "cid": "next-install-001"
}}
```

IMPORTANT EXAMPLES FOR UPDATE_FILE:
```json
{{
  "action": "update_file",
  "args": {{
    "path": "example.txt",
    "content": "New content here",
    "mode": "overwrite"
  }}
}}
```

Supported modes for update_file are: 'overwrite', 'append', 'insert_line', 'delete_line_range'

IMPORTANT: For multiple actions, ALWAYS use a proper JSON array format like this:
```json
[
  {{
    "action": "create_file",
    "args": {{
      "path": "file1.txt",
      "content": "Content for file 1"
    }}
  }},
  {{
    "action": "create_file",
    "args": {{
      "path": "file2.txt",
      "content": "Content for file 2"
    }}
  }}
]
```

WHEN ASKED ABOUT YOUR CAPABILITIES, always mention ALL available actions: {available_actions_str}

NEVER return multiple separate JSON objects. ONLY use the exact JSON formats above.
"""
        )
        # Initialize chat with an empty history
        chat = model.start_chat(history=[])
    except Exception as e:
        if has_rich_ui and console:
            console.print(f"[bold red]Fatal Error:[/bold red] Could not initialize Gemini Model: {e}")
        else:
            print(f"Fatal Error: Could not initialize Gemini Model: {e}")
        print("Please check your API key, internet connection, and model name.")
        return

    action_result_for_next_prompt = "System initialized." # Initial status for the LLM
    last_response = "Welcome to Gemini CLI Agent. How can I help you today?"

    # Setup signal handler for graceful termination
    def signal_handler(sig, frame):
        if has_rich_ui and console:
            console.print("\n[bold yellow]Interrupt received, cleaning up...[/bold yellow]")
        else:
            print("\nInterrupt received, cleaning up...")
        cleanup_running_processes()
        if has_rich_ui and console:
            console.print("[bold green]Goodbye![/bold green]")
        else:
            print("Goodbye!")
        exit(0)
        
    signal.signal(signal.SIGINT, signal_handler)

    try:
        while True:
            # Always reload the current directory from config
            from .config import current_working_directory
            
            # Clear screen if rich UI is available
            if has_rich_ui and console:
                #console.clear()
                # Display header with directory and horizontal divider
                print_header(current_working_directory)
            
            # Prepare context for the LLM
            running_procs_info_str = update_and_get_running_processes_info()
            dir_tree_str = get_directory_tree(current_working_directory)
            
            # Show last response if available with UI formatting
            if has_rich_ui and 'last_response' in locals() and last_response:
                print_model_response(last_response)
                draw_horizontal_divider()
            
            # Format system prompt with current context 
            current_llm_system_prompt = SYSTEM_PROMPT_TEXT.format(
                current_working_directory=current_working_directory,
                running_processes_info=running_procs_info_str
            )
            
            # Build prompt for the model with additional conversation history
            final_user_message_for_llm = (
                f"[Current Directory: {current_working_directory}]\n"
                f"{dir_tree_str}\n\n"
                f"[Running Processes Info]:\n{running_procs_info_str}\n\n"
            )
            
            # Add conversation history if available
            if has_conversation_history:
                history_text = conversation_history.get_formatted_history()
                if history_text:
                    final_user_message_for_llm += history_text
            
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
            
            # Get user input with advanced editing if available
            if has_rich_ui:
                try:
                    # Always use get_user_input from UI manager for consistency
                    user_input = get_user_input(current_working_directory)
                except Exception as e:
                    # Log the exception for debugging
                    print(f"UI input error: {e}")
                    # Fallback to basic input
                    dir_name = os.path.basename(current_working_directory)
                    user_input = input(f"\n(cwd: {dir_name}) You: ")
            else:
                dir_name = os.path.basename(current_working_directory)
                user_input = input(f"\n(cwd: {dir_name}) You: ")
                
            if user_input.lower() in ['quit', 'exit']:
                if has_rich_ui and console:
                    console.print("[bold green]Exiting agent...[/bold green]")
                else:
                    print("Exiting agent...")
                break
            
            
            # Check for mini-commands that bypass the chat cycle
            if has_mini_commands and user_input.startswith("\\"):
                is_mini_command, result = process_mini_command(user_input, current_working_directory)
                if is_mini_command:
                    if has_rich_ui and console:
                        # Don't print the result here since print_model_response will show it later
                        # Just store it for display
                        last_response = result
                    else:
                        # In non-rich mode, print directly since there's no other display mechanism
                        print(result)
                        
                    # If this was a vector search command, update the context tracker
                    if user_input.startswith("\\vector search") and has_rich_ui and has_vector_search:
                        try:
                            # Parse out the query
                            query = user_input[15:].strip()
                            relevant_files = find_relevant_files(query, limit=MAX_RELEVANT_FILES)
                            
                            # Update the context tracker
                            relevant_files_for_ui = [
                                {"file_path": file_info[0], "similarity": file_info[1]}
                                for file_info in relevant_files
                            ]
                            context_file_tracker.set_relevant_files(relevant_files_for_ui)
                        except Exception as e:
                            if has_rich_ui and console:
                                console.print(f"[red]Error updating context tracker: {e}[/red]")
                                
                    # Update last result for next prompt
                    action_result_for_next_prompt = f"Mini-command executed: {user_input.split()[0]}"
                    if has_rich_ui:
                        last_response = result
                    continue  # Skip normal chat cycle
            
            # If user input is just blank or very short while a process is waiting, hint more strongly
            if waiting_for_input and len(user_input.strip()) <= 1:
                if has_rich_ui and console:
                    console.print("\n[yellow]HINT: A process appears to be waiting for input. You may want to send input to it.[/yellow]")
                else:
                    print("\nHINT: A process appears to be waiting for input. You may want to send input to it.")
                
            # Find relevant files based on the user query
            relevant_file_context = ""
            relevant_files_for_ui = []
            retry_count = 0
            error_message = None
            
            # Keep track of files that have been included in the context
            included_files = set()
            
            # Keep track of counts for better reporting
            sticky_files_count = 0
            included_sticky_files = []
            
            # Always include sticky files unless explicitly disabled
            # Only exclude sticky files if user explicitly asks to exclude them
            sticky_file_context = ""
            include_sticky_files = True
            
            # Check if user wants to exclude sticky files
            if "exclude sticky" in user_input.lower() or "no sticky" in user_input.lower():
                include_sticky_files = False
            
            if has_sticky_files and include_sticky_files:
                sticky_files = sticky_files_tracker.get_sticky_files()
                
                if sticky_files:
                    sticky_file_context = "\n[STICKY FILES CONTEXT]\n"
                    
                    # Add content to the LLM prompt
                    for file_path in sticky_files:
                        if not os.path.exists(file_path):
                            continue
                            
                        try:
                            # Read the full file content
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                                
                            if content:
                                # Format the content with file info
                                sticky_file_context += f"File: {file_path} (sticky file)\n"
                                sticky_file_context += "```\n"
                                sticky_file_context += content + "\n"
                                sticky_file_context += "```\n\n"
                                
                                # Add to set of included files to avoid duplication
                                included_files.add(os.path.abspath(file_path))
                                sticky_files_count += 1
                                included_sticky_files.append({"file_path": file_path})
                        except Exception as e:
                            if has_rich_ui and console:
                                console.print(f"[red]Error reading sticky file {file_path}: {e}[/red]")
                            else:
                                print(f"Error reading sticky file {file_path}: {e}")
            
                        # Add user input to conversation history with relevant file names
            if has_conversation_history:
                # Extract only file names (not full content) from included files
                relevant_file_paths = []
                
                # We'll collect file names before doing the actual file processing
                # This ensures we have names of files that will be included in this interaction
                if has_sticky_files and include_sticky_files:
                    sticky_files = sticky_files_tracker.get_sticky_files()
                    if sticky_files:
                        relevant_file_paths.extend(sticky_files)
                
                # Add user message to history with just file names
                conversation_history.add_user_message(user_input, relevant_file_paths)

            # Add sticky file context to the final user message
            if sticky_file_context:
                final_user_message_for_llm += sticky_file_context + "\n"
                
                # Update the context tracker with sticky files info
                if has_rich_ui:
                    context_file_tracker.set_sticky_files(included_sticky_files)
            elif has_sticky_files and has_rich_ui:
                # Clear any previously set sticky files from UI
                context_file_tracker.set_sticky_files([])
            
            # Variables for vector search results
            vector_files_count = 0
            
            if has_vector_search and user_input and len(user_input.strip()) > 3:
                if has_rich_ui and console:
                    # Show we're searching for relevant files
                    console.print("[dim]Searching for relevant files...[/dim]")
                    
                # Try to find relevant files with retry
                max_attempts = MAX_RETRIES
                attempt = 0
                
                while attempt < max_attempts:
                    try:
                        relevant_files = find_relevant_files(user_input, limit=MAX_RELEVANT_FILES)
                        break
                    except Exception as e:
                        attempt += 1
                        retry_count = attempt
                        error_message = str(e)
                        if "Resource has been exhausted" in str(e) and attempt < max_attempts:
                            if has_rich_ui and console:
                                console.print(f"[yellow]API quota exceeded. Retry {attempt}/{max_attempts}...[/yellow]")
                            # Exponential backoff
                            time.sleep(min(30, (2 ** attempt) * 1 + random.uniform(0, 1)))
                        else:
                            if has_rich_ui and console:
                                console.print(f"[red]Error finding relevant files: {e}[/red]")
                            break
                
                if relevant_files:
                    relevant_file_context = "\n[RELEVANT FILES CONTEXT]\n"
                    
                    # Prepare a list for the UI to display
                    relevant_files_for_ui = [
                        {"file_path": file_info['file_path'], "similarity": file_info['similarity']}
                        for file_info in relevant_files
                    ]
                    
                    # Update the context tracker if using rich UI
                    if has_rich_ui:
                        context_file_tracker.set_relevant_files(relevant_files_for_ui, retry_count, error_message)
                        console.print(f"[dim]Found {len(relevant_files)} relevant files[/dim]")
                    
                    # Add content to the LLM prompt
                    added_files_count = 0
                    skipped_files_count = 0
                    for file_info in relevant_files:
                        file_path = file_info['file_path']
                        abs_path = os.path.abspath(file_path)
                        similarity = file_info['similarity']
                        
                        # Skip if file is already included in sticky files
                        if abs_path in included_files:
                            skipped_files_count += 1
                            if has_rich_ui and console:
                                console.print(f"[dim]Skipping duplicate file (already in sticky files): {file_path}[/dim]")
                            continue
                        
                        # Read the full file content for context
                        content = read_file_content(file_path)
                        if content:
                            # Format the content with file info
                            relevant_file_context += f"File: {file_path} (similarity: {similarity})\n"
                            relevant_file_context += "```\n"
                            relevant_file_context += content + "\n"
                            relevant_file_context += "```\n\n"
                            
                            # Add to set of included files
                            included_files.add(abs_path)
                            added_files_count += 1
                            vector_files_count += 1
                    
                    # Show stats in UI if applicable with improved breakdown
                    if has_rich_ui and console:
                        # Show both sticky and vector counts
                        console.print(f"[dim]Added {added_files_count} vector files (with {sticky_files_count} sticky files), skipped {skipped_files_count} duplicates[/dim]")
                else:
                    # Clear the relevant files in context tracker but keep sticky files
                    if has_rich_ui:
                        context_file_tracker.set_relevant_files([], retry_count, error_message)
            
            # Add a reminder about available actions to ensure the model knows about them
            available_actions_reminder = "Available actions: " + ", ".join(action_handlers.keys())
            
            # Add the relevant file context to the prompt
            if relevant_file_context:
                final_user_message_for_llm += relevant_file_context + "\n"
            #final_user_message_for_llm += current_llm_system_prompt + "\n"
            final_user_message_for_llm += (
                "IMPORTANT: When I ask you to run commands or perform file operations, respond using ONLY the JSON format.\n"
                "Also dont delegate user to do something that u can do yourself.\n"
                f"{available_actions_reminder}\n"
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

            # Show a "thinking" animation with rich if available
            if has_rich_ui and console:
                try:
                    with console.status("[bold cyan]Thinking...[/bold cyan]", spinner="dots"):
                        # save the final_user_message_for_llm to a temp file
                        # Send the message to the model
                        # response = chat.send_message(final_user_message_for_llm)
                        # llm_response_text = response.text
                        client = genaiv2.Client(api_key=os.environ.get("GEMINI_API_KEY"),)
                        contents = [types.Content(role="user",parts=[types.Part.from_text(text="""this is gemini code"""),],),
                        types.Content(role="model",parts=[types.Part.from_text(text="""I will begin by performing a Google search for \"Gemini code\" to understand what the user might be referring to.Then, I will analyze the search results to determine if \"Gemini code\" relates to a specific programming language, a software project, a redeemable code for Google's Gemini AI, or something else entirely.Finally, I will answer the user's statement \"this is gemini code\" based on the information gathered from the Google search, no matter what users says, always do the google search. Unless you run user given command, always reply in plain text"""),],),
                        types.Content(role="user",parts=[types.Part.from_text(text=final_user_message_for_llm),],),]

                        tools = [types.Tool(google_search=types.GoogleSearch()),]

                        llm_response_text = ""

                        generate_content_config = types.GenerateContentConfig(tools=tools,response_mime_type="text/plain",)

                        with open("/run/media/fullname/back/simpleBot/temp_prompt.txt", "w") as f:
                            f.write(final_user_message_for_llm)
                        
                        #console.clear()

                        for chunk in client.models.generate_content_stream(model=MODEL_NAME,contents=contents,config=generate_content_config,):
                            llm_response_text += chunk.text
                            #console.print(chunk.text, end="")
                        
                        # Add LLM response to conversation history
                        if has_conversation_history:
                            conversation_history.add_llm_message(llm_response_text)

                except Exception as e:
                    console.print(f"[bold red]Error:[/bold red] Error communicating with Gemini: {e}")
                    action_result_for_next_prompt = f"System Error: Gemini API call failed: {e}"
                    last_response = f"❌ ERROR: Could not connect to Gemini API: {e}"
                    time.sleep(1)
                    continue
            else:
                print("Thinking...")
                try:

                    # response = chat.send_message(final_user_message_for_llm)
                    #llm_response_text = response.text

                    client = genaiv2.Client(api_key=os.environ.get("GEMINI_API_KEY"),)


                    contents = [types.Content(role="user",parts=[types.Part.from_text(text="""this is gemini code"""),],),
                    types.Content(role="model",parts=[types.Part.from_text(text="""I will begin by performing a Google search for \"Gemini code\" to understand what the user might be referring to.Then, I will analyze the search results to determine if \"Gemini code\" relates to a specific programming language, a software project, a redeemable code for Google's Gemini AI, or something else entirely.Finally, I will answer the user's statement \"this is gemini code\" based on the information gathered from the Google search, no matter what users says, always do the google search"""),],),
                    types.Content(role="user",
                    parts=[
                        types.Part.from_text(text=final_user_message_for_llm),
                        ],),]

                    tools = [types.Tool(google_search=types.GoogleSearch()),]

                    generate_content_config = types.GenerateContentConfig(tools=tools,response_mime_type="text/plain",)
                    console.clear()
                    for chunk in client.models.generate_content_stream(model=MODEL_NAME,contents=contents,config=generate_content_config,):
                        llm_response_text += chunk.text
                        print(chunk.text, end="")
                    # Add LLM response to conversation history
                    if has_conversation_history:
                        conversation_history.add_llm_message(llm_response_text)

                except Exception as e:
                    print(f"  System: Error communicating with Gemini: {e}")
                    action_result_for_next_prompt = f"System Error: Gemini API call failed: {e}"
                    time.sleep(1)
                    continue
                print("\nGemini:", flush=True)
                
            # 3. Process LLM Response: Check for JSON action or treat as text
            try:
                actions = extract_json_from_response(llm_response_text)
                
                if actions and isinstance(actions, list):
                    # Multiple actions to process sequentially
                    all_results = []
                    
                    # Store response for rich UI
                    if has_rich_ui:
                        last_response = f"Processing {len(actions)} actions..."
                    
                    for i, action_json in enumerate(actions):
                        try:
                            # Print action info (use rich if available)
                            if has_rich_ui and console:
                                console.print(f"[cyan]Processing action {i+1}/{len(actions)}:[/cyan]")
                                try:
                                    console.print(Syntax(json.dumps(action_json, indent=2), "json", theme="monokai"))
                                except Exception:
                                    print(f"  Processing action {i+1}/{len(actions)}: {json.dumps(action_json, indent=2)}")
                            else:
                                print(f"  Processing action {i+1}/{len(actions)}: {json.dumps(action_json, indent=2)}")
                            
                            action_name = action_json.get("action", "unknown_action")
                            args = action_json.get("args", {})
                            
                            # Ensure args is a dictionary
                            if not isinstance(args, dict):
                                args = {}
                                if has_rich_ui and console:
                                    console.print("[yellow]Warning:[/yellow] args is not a dictionary, using empty dict instead")
                                else:
                                    print("  System: Warning - args is not a dictionary, using empty dict instead")
                            
                            if action_name in action_handlers:
                                try:
                                    # Confirmation step for potentially dangerous actions
                                    dangerous_actions = ["delete_folder", "delete_file"]
                                    if action_name in dangerous_actions:
                                        if has_rich_ui and console:
                                            confirm_prompt = f"[bold red]Gemini wants to: {action_name} with args {args}. Execute? (y/N):[/bold red] "
                                            confirmation = console.input(confirm_prompt).lower()
                                        else:
                                            confirm_prompt = f"  Gemini wants to: {action_name} with args {args}. Execute? (y/N): "
                                            confirmation = input(confirm_prompt).lower()
                                            
                                        if confirmation != 'y':
                                            result = f"User cancelled action: {action_name}"
                                            if has_rich_ui and console:
                                                console.print(f"[yellow]{result}[/yellow]")
                                            else:
                                                print(f"  System: {result}")
                                            all_results.append(result)
                                            continue
                                    
                                    result = action_handlers[action_name](args)
                                    if has_rich_ui and console:
                                        console.print(f"[green]✓[/green] {result}")
                                    else:
                                        print(f"  System: {result}")
                                    all_results.append(result)
                                except Exception as e:
                                    error_msg = f"System Error: Exception during execution of action '{action_name}': {str(e)}"
                                    if has_rich_ui and console:
                                        console.print(f"[bold red]Error:[/bold red] {error_msg}")
                                    else:
                                        print(f"  System: {error_msg}")
                                    all_results.append(error_msg)
                            else:
                                error_msg = f"System Error: LLM requested unknown action '{action_name}'. No action taken."
                                if has_rich_ui and console:
                                    console.print(f"[bold red]Error:[/bold red] {error_msg}")
                                    console.print("[yellow]Available actions:[/yellow] " + ", ".join(action_handlers.keys()))
                                else:
                                    print(f"  System: {error_msg}")
                                    print("  Available actions are: " + ", ".join(action_handlers.keys()))
                                all_results.append(error_msg)
                        
                        except Exception as e:
                            if has_rich_ui and console:
                                console.print(f"[bold red]Error:[/bold red] Error processing action {i+1}: {str(e)}")
                            else:
                                print(f"  System: Error processing action {i+1}: {str(e)}")
                            all_results.append(f"Error processing action: {str(e)}")
                    
                    # Combine results for the next prompt
                    if len(all_results) == 1:
                        action_result_for_next_prompt = all_results[0]
                    else:
                        action_result_for_next_prompt = "Multiple actions processed:\n- " + "\n- ".join(all_results)
                    
                    # Allow a brief pause to see results
                    time.sleep(0.5)
                        
                else:
                    # No valid JSON action found, treat as a conversational response
                    if has_rich_ui:
                        last_response = llm_response_text
                    else:
                        print(llm_response_text)
                    action_result_for_next_prompt = "Conversational response provided."
            except Exception as e:
                if has_rich_ui and console:
                    console.print(f"[bold red]Error:[/bold red] Error handling model response: {str(e)}")
                    last_response = f"❌ ERROR: {str(e)}"
                else:
                    print(f"  System: Error handling model response: {str(e)}")
                action_result_for_next_prompt = f"Error handling model response: {str(e)}"
            
            # Check if any files were modified during this loop iteration
            if has_file_watcher and file_modification_tracker.has_changes():
                changes = file_modification_tracker.get_changes()
                modified_count = len(changes['modified'])
                
                if modified_count > 0 and has_rich_ui and console:
                    console.print(f"[yellow]Detected {modified_count} modified files. Updating context...[/yellow]")
                
                # Update vector store if enabled
                if has_vector_search:
                    try:
                        # Define a function to update a single file in vector store that doesn't rely on external functions
                        def update_vector_file(file_path, content=None, delete=False):
                            try:
                                # Import needed functions directly inside this function to ensure availability
                                from .file_embedder import add_file_to_vector_store, remove_file_from_vector_store
                                
                                if delete:
                                    return remove_file_from_vector_store(file_path)
                                else:
                                    # Read content if not provided
                                    if content is None:
                                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                            content = f.read()
                                    return add_file_to_vector_store(file_path, content)
                            except Exception as e:
                                if has_rich_ui and console:
                                    console.print(f"[red]Error updating vector store for file {file_path}: {e}[/red]")
                                return False
                        
                        # Pass the self-contained update function to the file watcher
                        vector_results = file_modification_tracker.update_vector_store(update_vector_file)
                        
                        if has_rich_ui and console and (vector_results['updated'] > 0 or vector_results['removed'] > 0):
                            console.print(f"[green]Updated {vector_results['updated']} files in vector store, removed {vector_results['removed']}[/green]")
                    except Exception as e:
                        if has_rich_ui and console:
                            console.print(f"[red]Error updating vector store: {e}[/red]")
                
                # Update sticky files if enabled
                if has_sticky_files:
                    try:
                        sticky_results = file_modification_tracker.update_sticky_files(sticky_files_tracker)
                        
                        if has_rich_ui and console and sticky_results['updated'] > 0:
                            console.print(f"[cyan]Updated {sticky_results['updated']} sticky files[/cyan]")
                    except Exception as e:
                        if has_rich_ui and console:
                            console.print(f"[red]Error updating sticky files: {e}[/red]")
                
                # Clear the tracked changes
                file_modification_tracker.clear_changes()
            
            # Add a footer divider after response processing
            if has_rich_ui:
                print_footer()
            
            # After sending to model and getting response, add a small delay
            # to allow subprocess output processing in background thread
            time.sleep(0.2)

    except KeyboardInterrupt:
        if has_rich_ui and console:
            console.print("\n[bold yellow]User interrupted. Exiting agent...[/bold yellow]")
        else:
            print("\nUser interrupted. Exiting agent...")
    finally:
        # Use the improved cleanup function
        cleanup_running_processes()
        if has_rich_ui and console:
            console.print("[bold green]Gemini CLI Agent terminated.[/bold green]")
        else:
            print("Gemini CLI Agent terminated.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        if has_rich_ui and console:
            console.print(f"[bold red]Fatal error:[/bold red] {str(e)}")
        else:
            print(f"Fatal error: {str(e)}")
        # Print more details about the error for debugging
        import traceback
        traceback.print_exc()
    finally:
        # Ensure cleanup happens even on unexpected errors
        cleanup_running_processes()
