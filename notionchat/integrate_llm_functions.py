# integrate_llm_functions.py
# Integrates generated Notion API function files as COMMON TOOLS for sigoden/llm-functions.
# Copies tool file to tools/ directory.
# Appends tool filename to tools.txt.
# Runs argc build and link.

import os
import sys
import subprocess
import argparse
import glob
import shutil
import re # For sanitizing agent name (still useful for deriving tool name)

def sanitize_tool_name(db_name):
    """Creates a filesystem-safe tool name prefix from the database name."""
    # Similar to agent name, but maybe used differently if needed
    s = re.sub(r'[^\w\s-]', '', db_name.lower())
    s = re.sub(r'[-\s]+', '_', s).strip('_')
    if not s:
        return "unnamed_db"
    return s

def find_common_tool_files(search_dir):
    """Finds potential common tool files (*_tool.py) in a directory."""
    # Assuming generator output follows *_tool.py pattern now
    pattern = os.path.join(search_dir, '*_tool.py')
    files = glob.glob(pattern)
    # Return only the basenames
    return [os.path.basename(f) for f in files]

def run_command(command, working_dir):
    """Runs a shell command in a specified directory and checks for errors."""
    print(f"Running command: `{' '.join(command)}` in `{working_dir}`")
    try:
        use_shell = sys.platform == "win32"
        result = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=False,
            shell=use_shell,
            encoding='utf-8'
        )
        print("--- STDOUT ---")
        print(result.stdout)
        print("--- STDERR ---")
        print(result.stderr)
        if result.returncode != 0:
            print(f"Error: Command failed with return code {result.returncode}")
            return False
        return True
    except FileNotFoundError:
        print(f"Error: Command not found: '{command[0]}'. Is argc installed and in PATH?")
        return False
    except Exception as e:
        print(f"Error running command `{' '.join(command)}`: {e}")
        return False

def update_tools_txt(tools_txt_path, tool_filename):
    """Adds the tool FILENAME to tools.txt if it's not already present."""
    # NOTE: We are now adding only the filename, assuming argc build looks in tools/ implicitly.
    entry_to_add = tool_filename # Just the filename
    try:
        existing_tools = set()
        if os.path.exists(tools_txt_path):
            with open(tools_txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped_line = line.strip()
                    # Check against existing entries (could be just filename or tools/filename)
                    # For robustness, check if the filename part matches
                    existing_filename = os.path.basename(stripped_line.replace('\\', '/'))
                    if existing_filename:
                        existing_tools.add(existing_filename)

        # Check if the base filename is already effectively listed
        if entry_to_add not in existing_tools:
            print(f"Appending FILENAME '{entry_to_add}' to {tools_txt_path}")
            with open(tools_txt_path, 'a', encoding='utf-8') as f:
                f.write(f"{entry_to_add}\n") # Add filename and newline
            return True
        else:
            print(f"Tool filename '{entry_to_add}' already effectively listed in {tools_txt_path}. Skipping append.")
            return True # Still considered success
    except Exception as e:
        print(f"Error updating {tools_txt_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Integrates ONE generated Notion API common tool file with sigoden/llm-functions."
    )
    parser.add_argument(
        "llm_functions_dir",
        help="Path to the root directory of your cloned sigoden/llm-functions repository."
    )
    parser.add_argument(
        "client_files_dir",
        help="Path to the directory containing the single generated *_tool.py file."
    )
    parser.add_argument(
        "--skip-link",
        action="store_true",
        help="Skip the 'argc link-to-aichat' step."
    )

    args = parser.parse_args()

    llm_repo_path = os.path.abspath(args.llm_functions_dir)
    clients_path = os.path.abspath(args.client_files_dir)
    tools_dir_path = os.path.join(llm_repo_path, "tools") # Target is the 'tools' directory
    tools_txt_path = os.path.join(llm_repo_path, "tools.txt") # Path to tools.txt

    # --- Validate Paths ---
    if not os.path.isdir(llm_repo_path):
        print(f"Error: llm-functions directory not found: {llm_repo_path}")
        sys.exit(1)
    if not os.path.isdir(clients_path):
        print(f"Error: Client files directory not found: {clients_path}")
        sys.exit(1)

    # --- Find Client Tool File(s) ---
    print(f"Scanning for common tool files (*_tool.py) in: {clients_path}")
    tool_files = find_common_tool_files(clients_path)

    if not tool_files:
        print(f"Error: No common tool files (*_tool.py) found in {clients_path}.")
        sys.exit(1)
    if len(tool_files) > 1:
        print(f"Warning: Found multiple tool files in {clients_path}. Processing only the first one: {tool_files[0]}")

    tool_file = tool_files[0] # Process only the first one found
    print(f"Found tool file: {tool_file}")

    # --- Ensure tools directory exists ---
    os.makedirs(tools_dir_path, exist_ok=True)

    # --- Copy Tool File ---
    source_path = os.path.join(clients_path, tool_file)
    dest_path = os.path.join(tools_dir_path, tool_file)
    integration_errors = False
    try:
        shutil.copy2(source_path, dest_path)
        print(f"Copied {tool_file} to {tools_dir_path}")
    except Exception as e:
        print(f"Error copying file {tool_file}: {e}")
        integration_errors = True

    if integration_errors:
        print("\nErrors occurred during file copying. Skipping further steps.")
        sys.exit(1)

    # --- Update tools.txt ---
    # Add ONLY the filename to tools.txt
    tool_filename_to_add = tool_file
    if not update_tools_txt(tools_txt_path, tool_filename_to_add):
        print("Error updating tools.txt. Skipping build steps.")
        sys.exit(1)

    # --- Run argc build ---
    print("\n--- Running argc build ---")
    if not run_command(["argc", "build"], working_dir=llm_repo_path):
        print("Error during 'argc build'. Please check output.")
        sys.exit(1)
    print("'argc build' completed successfully.")

    # --- Run argc link-to-aichat (Optional, if needed) ---
    if not args.skip_link:
        print("\n--- Running argc link-to-aichat ---")
        if not run_command(["argc", "link-to-aichat"], working_dir=llm_repo_path):
            print("Error during 'argc link-to-aichat'. Please check output.")
        else:
            print("'argc link-to-aichat' completed.")
    else:
        print("\nSkipping 'argc link-to-aichat'.")

    print("\nIntegration script finished.")
    # Use the filename added to tools.txt in the final message
    print(f"Tool '{tool_filename_to_add}' should now be integrated.")
    print(f"*** Ensure Flask API ('flask_api_generator.py') is running for the correct database before testing. ***")
    print(f"*** Test using: aichat --role %functions% \"<your query related to {tool_filename_to_add.replace('_tool.py','')}>\" ***")


if __name__ == "__main__":
    main()

