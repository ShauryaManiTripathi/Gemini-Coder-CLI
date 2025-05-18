import os
import time
import subprocess
import queue
import threading
from .config import running_processes
from .process_manager import enqueue_output, update_specific_process_output, find_process_by_pid_or_cid

def handle_run_command(args):
    # Don't cache current_working_directory - always import it fresh to get latest value
    from .config import current_working_directory
    
    try:
        command_string = args.get("command_string")
        if not command_string: return "Error: 'command_string' is required for run_command."
        cid = args.get("cid", "")  # Use empty string instead of None for missing CID
        interactive = args.get("interactive", True)  # Default to interactive mode
        
        # Check if this is a cd command - we should redirect to change_directory
        if command_string.strip().startswith("cd "):
            from .file_operations import handle_change_directory
            target_dir = command_string.strip()[3:].strip()
            print(f"  System: Converting 'cd {target_dir}' command to change_directory action")
            return handle_change_directory({"path": target_dir})
        
        # Get the current normalized directory - always get it fresh from the config
        from .config import current_working_directory as current_dir
        current_dir = os.path.normpath(current_dir)
        
        # Print command being executed for clarity
        print(f"  Executing: {command_string}")
        print(f"  Working directory: {current_dir} (/run/media{current_dir})")
        
        if interactive:
            # Run in foreground interactive mode - let user directly interact
            print("\n--- Starting interactive process - Ctrl+C to return to agent ---")
            try:
                # Use os.system for interactive commands - this will allow direct user interaction
                # IMPORTANT: Always use the current directory from config
                exit_code = os.system(f"cd {current_dir} && {command_string}")
                print(f"\n--- Process completed with exit code: {exit_code} ---")
                return f"Command '{command_string}' completed with exit code {exit_code}"
            except KeyboardInterrupt:
                print("\n--- Interactive process interrupted ---")
                return f"Command '{command_string}' was interrupted by user"
        else:
            # Original background process mode with threading and queue
            # Always use the current working directory from config
            process = subprocess.Popen(
                command_string,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=current_dir,  # Use the fresh current_dir value
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
        return f"Error running command '{args.get('command_string')}': Command not found or path issue. {str(e)}"
    except Exception as e:
        return f"Error running command '{args.get('command_string')}': {str(e)}"

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
