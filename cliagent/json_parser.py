import re
import json

def extract_json_from_response(text):
    """Extract and normalize JSON actions from model responses with robust error handling"""
    try:
        # First, check for arrays that start with [ and contain multiple actions
        array_match = re.search(r"\[\s*\{\s*\"action\"", text)
        if array_match:
            # Try to extract the entire JSON array
            try:
                # Find the opening [
                start_index = text.find('[', array_match.start())
                if start_index != -1:
                    # Find the matching closing ]
                    bracket_count = 1
                    end_index = start_index + 1
                    while end_index < len(text) and bracket_count > 0:
                        if text[end_index] == '[':
                            bracket_count += 1
                        elif text[end_index] == ']':
                            bracket_count -= 1
                        end_index += 1
                    
                    if bracket_count == 0:
                        json_array = text[start_index:end_index]
                        try:
                            actions = json.loads(json_array)
                            if isinstance(actions, list):
                                # Normalize each action in the array
                                normalized_actions = []
                                for action in actions:
                                    if isinstance(action, dict):
                                        normalized_action = normalize_action_object(action)
                                        if normalized_action:
                                            normalized_actions.append(normalized_action)
                                return normalized_actions
                        except json.JSONDecodeError:
                            print("  System: Failed to parse JSON array directly, falling back to regular parsing")
            except Exception as e:
                print(f"  System: Error extracting array: {e}")
                
        # Attempt to find JSON within ```json ... ``` markdown block
        match = re.search(r"```json\s*([\s\S]*?)\s*```", text)
        if match:
            json_str = match.group(1)
            
            # Check for array format first - this is the most common case for multiple actions
            if json_str.strip().startswith('['):
                try:
                    json_obj = json.loads(json_str)
                    if isinstance(json_obj, list):
                        # Process array directly
                        normalized_actions = []
                        for i, action_item in enumerate(json_obj):
                            if isinstance(action_item, dict):
                                normalized_action = normalize_action_object(action_item)
                                if normalized_action:
                                    normalized_actions.append(normalized_action)
                        
                        print(f"  System: Processed array of {len(normalized_actions)} actions")
                        return normalized_actions
                except Exception as e:
                    print(f"  System: Error processing JSON array: {e}")
            
            # Check if we have multiple adjacent JSON objects
            if json_str.strip().startswith('{') and re.search(r'}\s*{', json_str):
                print("  System: Detected multiple adjacent JSON objects, converting to array format")
                # Fix the format by wrapping in array brackets
                json_str = '[' + re.sub(r'}\s*{', '},{', json_str) + ']'
            
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
                # Special handling for multiple adjacent JSON objects
                if '}{' in json_str:
                    print("  System: Attempting to fix malformed JSON with multiple objects")
                    try:
                        # Try to fix by turning it into a proper JSON array
                        fixed_json = '[' + re.sub(r'}\s*{', '},{', json_str) + ']'
                        json_obj = json.loads(fixed_json)
                        print("  System: Successfully converted multiple objects to array")
                        
                        # Convert to list of normalized actions
                        normalized_actions = []
                        for i, action_item in enumerate(json_obj):
                            if isinstance(action_item, dict):
                                normalized_action = normalize_action_object(action_item)
                                if normalized_action:
                                    normalized_actions.append(normalized_action)
                        
                        return normalized_actions
                    except Exception as fix_error:
                        print(f"  System: Failed to fix multiple JSON objects: {fix_error}")
                
                print(f"  System: Invalid JSON in markdown block: {e}. Content: '{json_str[:100]}...'")
                return None
            except Exception as e:
                print(f"  System: Error processing JSON: {str(e)}")
                return None
        
        # Fallback: if the entire response is just the JSON object(s)
        if text and isinstance(text, str) and text.strip().startswith(("{", "[")):
            try:
                # Check if text starts with an array
                if text.strip().startswith('['):
                    try:
                        # Extract JSON array from the beginning of text
                        # Find the matching closing bracket
                        bracket_count = 1
                        start_index = text.find('[')
                        end_index = start_index + 1
                        
                        while end_index < len(text) and bracket_count > 0:
                            if text[end_index] == '[':
                                bracket_count += 1
                            elif text[end_index] == ']':
                                bracket_count -= 1
                            end_index += 1
                        
                        if bracket_count == 0:
                            json_array = text[start_index:end_index]
                            actions = json.loads(json_array)
                            
                            if isinstance(actions, list):
                                normalized_actions = []
                                for action in actions:
                                    if isinstance(action, dict):
                                        normalized_action = normalize_action_object(action)
                                        if normalized_action:
                                            normalized_actions.append(normalized_action)
                                            
                                print(f"  System: Extracted {len(normalized_actions)} actions from raw array")
                                return normalized_actions
                    except Exception as e:
                        print(f"  System: Failed to extract array directly: {e}")
            
                # Check for multiple JSON objects and fix if needed
                if text.strip().startswith('{') and re.search(r'}\s*{', text):
                    print("  System: Detected multiple JSON objects in raw text, converting to array")
                    text = '[' + re.sub(r'}\s*{', '},{', text) + ']'
                
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
    
    # Special handling for directory changes via run_command
    if action == "run_command" and isinstance(action_obj.get("args"), dict):
        cmd = action_obj["args"].get("command_string", "")
        if isinstance(cmd, str) and cmd.strip().startswith("cd "):
            # Convert to change_directory action
            target_dir = cmd.strip()[3:].strip()
            print(f"  System: Converting run_command 'cd {target_dir}' to change_directory action")
            action_obj["action"] = "change_directory"
            action_obj["args"] = {"path": target_dir}
    
    # Normal action name normalization
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
    
    # Log the normalized action for better transparency
    print(f"  System: Using normalized action: '{action_name}' with args: {args}")
    
    return action_obj
