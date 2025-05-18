import os
import pathlib

# Don't import current_working_directory directly - always get it fresh

def get_directory_tree(startpath_str):
    startpath = pathlib.Path(startpath_str)
    tree_str = f"Directory tree for: {startpath.resolve()}\n"
    MAX_DEPTH = 4
    MAX_ITEMS_PER_DIR = 15
    entries_count = 0
    
    # Comprehensive list of directories to not traverse deeply
    SKIP_DEEP_TRAVERSE = {
        # Node.js / JavaScript / TypeScript
        'node_modules', 'bower_components', '.npm', '.next', '.nuxt', 'dist', 'build',
        '.cache', '.parcel-cache', '.webpack', '.angular', '.yarn',
        
        # Python
        '.venv', 'venv', 'env', '__pycache__', '.pytest_cache', '.tox', '.eggs', '.mypy_cache',
        '.coverage', 'site-packages', '.ipynb_checkpoints',
        
        # Java / JVM
        'target', '.gradle', '.m2', '.ivy2', 'out', 'bin', 'classes', '.settings', 
        '.idea', '.metadata', '.plugins',
        
        # Ruby / Rails
        'vendor/bundle', '.bundle', 'tmp/cache',
        
        # PHP / Composer
        'vendor', 'composer', 
        
        # Go
        'pkg', 'vendor', '.go-cache',
        
        # Rust
        'target', '.cargo', 
        
        # Containers
        '.docker', '.containers',
        
        # Version control
        '.git', '.svn', '.hg', '.bzr',
        
        # IDE / Editor
        '.idea', '.vs', '.vscode', '.fleet', '.atom', '.eclipse',
        
        # Build systems / bundlers
        'dist', 'build', 'public/build', 'out', 'output', 
        
        # CI/CD
        '.gitlab', '.github', '.circleci',
        
        # Logs / temp
        'logs', 'log', 'tmp', 'temp',
        
        # Compiled code
        'bin', 'obj',
        
        # macOS
        '.DS_Store',
        
        # Unity
        'Library', 'Temp', 'obj', 'Logs',
        
        # Flutter / Dart
        '.dart_tool', '.pub', 'build',
        
        # .NET / C#
        'obj', 'bin', 'packages', '.vs',
    }

    def _get_tree_recursive(current_path, prefix="", current_level=0):
        nonlocal tree_str, entries_count
        if current_level > MAX_DEPTH:
            tree_str += prefix + "└── [Reached Max Depth]\n"
            return
            
        # Check if current directory is in skip list
        if current_path.name in SKIP_DEEP_TRAVERSE and current_level > 0:
            tree_str += prefix + "└── " + current_path.name + "/ [Module/Cache Directory]\n"
            return

        try:
            # Get all items, sort dirs first, then by name
            paths = sorted(list(current_path.iterdir()), 
                           key=lambda p: (not p.is_dir(), p.name.lower()))
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
            
            # Mark directory/file properly
            suffix = "/" if path_obj.is_dir() else ""
            
            # Check if this is a module/cache directory that shouldn't be traversed deeply
            if path_obj.is_dir() and path_obj.name in SKIP_DEEP_TRAVERSE:
                tree_str += prefix + pointer + path_obj.name + suffix + " [Module/Cache Directory]\n"
                continue
                
            tree_str += prefix + pointer + path_obj.name + suffix + "\n"
            
            if path_obj.is_dir():
                if entries_count > 200: # Overall limit on tree entries
                    if i == len(display_paths) -1:
                        tree_str += prefix + "    └── [Tree too large, further items omitted]\n"
                    else:
                        tree_str += prefix + "│   └── [Tree too large, further items omitted]\n"
                    continue # Stop adding more branches if tree is huge

                extender = "│   " if pointer == '├── ' else "    "
                _get_tree_recursive(path_obj, prefix + extender, current_level + 1)
        
        if is_truncated:
            tree_str += prefix + ("    " if pointers[-1] == '└── ' else "│   ") + f"... and {len(paths) - MAX_ITEMS_PER_DIR} more items\n"


    _get_tree_recursive(startpath)
    return tree_str.strip()

def resolve_path(path_str):
    """Resolves a path string to an absolute path using the current working directory"""
    # Always get the freshest version of current_working_directory
    from .config import current_working_directory
    
    # Expands user (~), makes path absolute if not already, and joins with CWD if relative
    expanded_path = os.path.expanduser(str(path_str))  # Ensure path_str is string
    if os.path.isabs(expanded_path):
        return os.path.normpath(expanded_path)
    
    # Get the latest current_working_directory and join with it
    return os.path.normpath(os.path.join(current_working_directory, expanded_path))
