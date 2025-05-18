import pexpect
import io

def run_and_capture(cmd, cwd):
    # spawn with a real pty for interactivity
    child = pexpect.spawn(cmd, cwd=cwd, encoding='utf-8')

    # buffer to hold everything the child prints
    capture_buf = io.StringIO()
    child.logfile_read = capture_buf      # <-- attach reader
    child.logfile = None                  # optional: if you don't want to log user keystrokes

    print("\n--- Interactive shell started (quit with Ctrl+\\ then Ctrl+D) ---")
    child.interact()                      # hand control to the user

    # once the user quits, EOF will occur
    child.expect(pexpect.EOF)             # wait for the child to finish
    exit_code = child.exitstatus

    full_output = capture_buf.getvalue()  # everything the child printed
    return exit_code, full_output

if __name__ == "__main__":
    code, output = run_and_capture("pnpm create t3-app@latest .", ".")
    print(f"\n>>> Exit code: {code}")
    print(">>> Captured output:\n", output)
