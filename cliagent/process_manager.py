import os
import time
import subprocess
import threading
import select
import queue
# Only import running_processes, not current_working_directory
from .config import running_processes

def update_and_get_running_processes_info():
    # Always get the most current working directory
    from .config import current_working_directory
    
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
