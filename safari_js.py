"""Run JavaScript in Safari and return the result."""
from __future__ import annotations
import subprocess
import sys

def run_js(code: str) -> str:
    """Execute JS in Safari's current document and return the string result."""
    # Use a temp file to avoid quoting issues with osascript
    import tempfile, os
    js_file = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False)
    js_file.write(code)
    js_file.close()

    applescript = f'''
    set jsCode to read POSIX file "{js_file.name}"
    tell application "Safari"
        do JavaScript jsCode in document 1
    end tell
    '''
    try:
        r = subprocess.run(['osascript', '-e', applescript],
                          capture_output=True, text=True, timeout=10)
        return r.stdout.strip()
    finally:
        os.unlink(js_file.name)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        print(run_js(sys.argv[1]))
    else:
        import fileinput
        code = ''.join(fileinput.input())
        print(run_js(code))
