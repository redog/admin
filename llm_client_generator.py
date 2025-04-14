# llm_client_generator.py
# Generates a Python script with a SINGLE 'run' function for sigoden/llm-functions (Common Tool format).

import os
import sys
import json
import argparse
from typing import List, Dict, Optional, Any, Union, Literal
from notion_client import Client, APIResponseError
import re

# --- Notion Client Initialization ---
NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
if not NOTION_API_TOKEN:
    print("Error: Missing Notion API key. Set NOTION_API_TOKEN in your environment.", file=sys.stderr)
    exit(1)

try:
    notion = Client(auth=NOTION_API_TOKEN)
    print(" * Notion client initialized successfully.", file=sys.stderr)
except Exception as e:
    print(f"Error: Failed to initialize Notion client: {e}", file=sys.stderr)
    exit(1)

# --- DB Fetch/Select Functions ---
def fetch_databases():
    """Fetches accessible databases from Notion."""
    print(" * Fetching accessible databases from Notion...", file=sys.stderr)
    try:
        # Use pagination to fetch all databases if there are more than 100
        all_databases = []
        start_cursor = None
        while True:
            response = notion.search(
                filter={"property": "object", "value": "database"},
                page_size=100, # Notion API max page size is 100
                start_cursor=start_cursor
            )
            results = response.get("results", [])
            for db in results:
                # Ensure it's a database object and has a title
                if db.get("object") == "database" and db.get("title"):
                    # Extract the plain text title
                    title_list = db.get("title", [])
                    if title_list:
                        db_name = title_list[0].get("plain_text", "Untitled Database")
                        db_id = db.get("id")
                        if db_id: # Ensure ID exists
                            all_databases.append({"name": db_name, "id": db_id})

            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
            else:
                break # Exit loop if no more pages

        print(f" * Found {len(all_databases)} databases.", file=sys.stderr)
        return all_databases
    except APIResponseError as error:
         print(f"Error fetching databases from Notion: {error}", file=sys.stderr)
         return None
    except Exception as e:
        # Return None and let the main block handle JSON error output
        print(f"Error during database fetch: {e}", file=sys.stderr) # Print to stderr
        return None

def display_databases_and_get_choice(databases):
    """Displays the list of databases and prompts the user for selection."""
    if not databases:
        print("Error: No databases found or accessible.", file=sys.stderr)
        return None

    # Use stderr for prompts so stdout contains only the generated code
    print("\nSelect a Notion database to generate a tool file for:", file=sys.stderr) # Updated prompt
    for i, db in enumerate(databases):
        print(f"{i + 1}. {db.get('name', 'N/A')} (ID: {db.get('id', 'N/A')})", file=sys.stderr)

    while True:
        # Print the prompt to stderr explicitly
        print("Enter the number: ", end="", file=sys.stderr, flush=True)
        try:
            # Call input() without a prompt string
            choice = input()
            index = int(choice) - 1
            if 0 <= index < len(databases):
                selected_db = databases[index]
                print(f" * Generating tool file for: {selected_db.get('name')} ({selected_db.get('id')})", file=sys.stderr)
                return selected_db # Return the full dictionary
            else:
                print("Invalid selection. Please enter a number from the list.", file=sys.stderr)
        except ValueError:
            print("\nInvalid input. Please enter a number.", file=sys.stderr) # Add newline for clarity after bad input
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.", file=sys.stderr)
            return None
        except EOFError: # Handle case where input stream is closed unexpectedly
             print("\nInput stream closed unexpectedly.", file=sys.stderr)
             return None

def get_database_properties(database_id):
    """Retrieves the full properties schema for a given database ID."""
    print(f" * Retrieving schema for database ID: {database_id}...", file=sys.stderr)
    try:
        database = notion.databases.retrieve(database_id=database_id)
        # Return the entire 'properties' dictionary
        properties_schema = database.get('properties', {})
        print(" * Schema retrieved successfully.", file=sys.stderr)
        return properties_schema
    except APIResponseError as error:
         print(f"Error retrieving schema for DB ID {database_id}: {error}", file=sys.stderr)
         return None
    except Exception as e:
        # Return None on error, let caller handle JSON output
        print(f"Error retrieving properties for DB ID {database_id}: {e}", file=sys.stderr) # Print to stderr
        return None


# --- Helper to generate 'run' function signature and docstring args ---
def generate_run_function_details(schema_props):
    """Generates the signature parameters and Args section for the single 'run' function."""
    sig_params = []
    doc_args_lines = []
    processed_params = set()
    param_name_map = {} # Map pythonic name back to original Notion name

    # 1. Action Parameter (Required)
    actions = ["list", "get", "create", "update", "delete"]
    actions_literal = ", ".join([f'"{a}"' for a in actions])
    sig_params.append(f"action: Literal[{actions_literal}]")
    doc_args_lines.append(f"        action: The operation to perform. Must be one of: {actions_literal}.")
    processed_params.add("action")
    param_name_map["action"] = "action" # Not a Notion prop

    # 2. Page ID Parameter (Optional overall, but required for some actions)
    sig_params.append("page_id: Optional[str] = None")
    doc_args_lines.append("        page_id: The Notion Page ID (required for 'get', 'update', 'delete' actions).")
    processed_params.add("page_id")
    param_name_map["page_id"] = "page_id" # Not a Notion prop

    # 3. Parameters derived from Schema Properties (all optional in signature)
    title_prop_name = None
    title_param_name = None

    sorted_prop_names = sorted(schema_props.keys()) # Sort for consistent order

    for prop_name in sorted_prop_names:
        prop_details = schema_props[prop_name]
        prop_type = prop_details['type']

        # Find and store title property details
        if prop_type == 'title':
            title_prop_name = prop_name
            title_param_name = ''.join(c if c.isalnum() else '_' for c in prop_name.lower()).strip('_')
            if not title_param_name: title_param_name = 'title_prop'
            if title_param_name.startswith('_'): title_param_name = 'p' + title_param_name
            processed_params.add(title_param_name)
            param_name_map[title_param_name] = title_prop_name
            sig_params.append(f"{title_param_name}: Optional[str] = None")
            doc_args_lines.append(f"        {title_param_name}: Value for the '{title_prop_name}' (title) property (required for 'create').")
            continue

        read_only_types = ['formula', 'rollup', 'created_time', 'last_edited_time', 'created_by', 'last_edited_by']
        if prop_type in read_only_types:
            continue

        python_type = "Any"
        description_suffix = ""
        # Type mapping - Using Optional[float] as it seemed to pass build last time
        if prop_type in ['rich_text', 'email', 'phone_number', 'url']: python_type = "str"
        elif prop_type == 'number': python_type = "float" # Use float for number type
        elif prop_type == 'select':
            options = prop_details.get('select', {}).get('options', [])
            valid_options = [opt["name"] for opt in options if opt.get("name")]
            if valid_options:
                 options_literal = ", ".join([f'"{name}"' for name in valid_options])
                 python_type = f'Literal[{options_literal}]'
                 description_suffix = f" # Must be one of the specified literals."
            else: python_type = "str"
        elif prop_type == 'multi_select':
             python_type = "List[str]"
             options = prop_details.get('multi_select', {}).get('options', [])
             valid_options = [opt["name"] for opt in options if opt.get("name")]
             if valid_options: description_suffix = f" # List of strings. Valid options: {valid_options}"
        elif prop_type == 'date': python_type = "str"; description_suffix = " # Format: YYYY-MM-DD"
        elif prop_type == 'checkbox': python_type = "bool"
        elif prop_type == 'people' or prop_type == 'relation': python_type = "List[str]"; description_suffix = " # List of Notion User/Page IDs"
        elif prop_type == 'files': python_type = "List[str]"; description_suffix = " # List of file names (API limitations apply)"
        elif prop_type == 'status':
             options = prop_details.get('status', {}).get('options', [])
             valid_options = [opt["name"] for opt in options if opt.get("name")]
             if valid_options:
                 options_literal = ", ".join([f'"{name}"' for name in valid_options])
                 python_type = f'Literal[{options_literal}]'
                 description_suffix = f" # Must be one of the specified literals."
             else: python_type = "str"

        # Parameter name (Pythonic, ensure uniqueness)
        base_param_name = ''.join(c if c.isalnum() else '_' for c in prop_name.lower()).strip('_')
        if not base_param_name: base_param_name = f"prop_{prop_details.get('id','').replace('%','_')}"
        if base_param_name.startswith('_'): base_param_name = 'p' + base_param_name
        param_name = base_param_name
        counter = 1
        while param_name in processed_params:
             param_name = f"{base_param_name}_{counter}"
             counter += 1
        processed_params.add(param_name)
        param_name_map[param_name] = prop_name

        # Add as optional parameter to signature and docstring
        sig_params.append(f"{param_name}: Optional[{python_type}] = None")
        doc_args_lines.append(f"        {param_name}: Value for '{prop_name}'. Used for filtering in 'list', or setting value in 'create'/'update'.{description_suffix}")

    signature_string = ",\n    ".join(sig_params)
    docstring_args_string = "\n".join(doc_args_lines)

    if title_prop_name is None:
         raise ValueError("Could not find a 'title' property in the database schema.")

    return signature_string, docstring_args_string, param_name_map, title_prop_name


# --- Main Generator Logic ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generates a Python common tool file (single 'run' function) for a selected Notion database Flask API.",
        epilog="Outputs the generated Python code to stdout. Redirect to a file (e.g., > db_tool.py)."
    )
    parser.add_argument(
        "--api-url-base",
        default="http://127.0.0.1:5002",
        help="The base URL where the Flask API server is running."
    )
    args = parser.parse_args()
    FLASK_API_BASE_URL = args.api_url_base.rstrip('/')

    # --- Select Database and Get Schema ---
    SCHEMA = None; selected_db_info = None
    available_databases = fetch_databases()
    if available_databases: selected_db_info = display_databases_and_get_choice(available_databases)
    if selected_db_info:
        properties = get_database_properties(selected_db_info["id"])
        if properties: SCHEMA = {"database_id": selected_db_info["id"], "database_name": selected_db_info["name"], "properties": properties}

    if not SCHEMA: print("Exiting due to schema error.", file=sys.stderr); exit(1)

    # --- Dynamic Values ---
    DATABASE_NAME = SCHEMA['database_name']
    PROPERTIES_SCHEMA = SCHEMA['properties']
    DB_NAME_SLUG = ''.join(c if c.isalnum() else '_' for c in DATABASE_NAME.lower()).strip('_')
    if not DB_NAME_SLUG: DB_NAME_SLUG = SCHEMA['database_id'].replace('-','_')
    API_ENDPOINT_PATH = f"{FLASK_API_BASE_URL}/api/{DB_NAME_SLUG}"
    TOOL_NAME = f"{DB_NAME_SLUG}_tool"

    # --- Generate Signature & Docstring ---
    try:
        run_sig, run_doc_args, param_map, title_prop_name = generate_run_function_details(PROPERTIES_SCHEMA)
    except ValueError as e:
        print(f"Error generating function details: {e}", file=sys.stderr)
        exit(1)

    # --- Generate Code Strings ---
    # Shebang line added
    shebang = "#!/usr/bin/env python3"

    helper_code = f"""
import requests
import json
import sys
from typing import List, Dict, Optional, Any, Union, Literal

# --- Configuration (Filled by Generator) ---
API_BASE_URL = "{API_ENDPOINT_PATH}"
DATABASE_NAME = "{DATABASE_NAME}"
PARAM_MAP = {param_map!r}
TITLE_PROP_NAME = "{title_prop_name}"
HEADERS = {{'Content-Type': 'application/json', 'Accept': 'application/json'}}

# --- Internal Request Helper ---
def _request(method: str, endpoint: str = "", **kwargs) -> Dict[str, Any] | List[Dict[str, Any]]:
    \"\"\"Internal helper for making requests to the Flask API.\"\"\"
    url = f"{{API_BASE_URL}}{{endpoint}}"
    print(f"--- TOOL DEBUG: Calling {{method}} {{url}} with params={{kwargs.get('params')}} json={{kwargs.get('json')}}", file=sys.stderr)
    try:
        response = requests.request(method, url, headers=HEADERS, **kwargs)
        print(f"--- TOOL DEBUG: API Response Status: {{response.status_code}}", file=sys.stderr)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
             if method.upper() == 'DELETE': return {{"message": f"Item successfully deleted/archived.", "status_code": response.status_code}}
             else: return {{}}
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        error_details = {{"error": f"HTTP Error: {{http_err.response.status_code}}", "url": url, "db": DATABASE_NAME}}
        try: error_details.update(http_err.response.json())
        except json.JSONDecodeError: error_details["message"] = http_err.response.text
        print(f"API Request Failed: {{error_details}}", file=sys.stderr)
        return error_details
    except requests.exceptions.RequestException as req_err:
        print(f"Request Failed: {{req_err}}", file=sys.stderr)
        return {{"error": "Request Exception", "message": str(req_err), "db": DATABASE_NAME}}
"""

    run_function_code = f"""
def run(
    {run_sig}
) -> Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]:
    \"\"\"
    Tool to interact with the '{DATABASE_NAME}' Notion database. Performs list, get, create, update, or delete actions.

    Args:
{run_doc_args}

    Returns:
        Optional[Union[List[Dict[str, Any]], Dict[str, Any]]]: Result from the API.
            - List of items for 'list' action.
            - Single item dictionary for 'get', 'create', 'update'.
            - Success/status dictionary for 'delete'.
            - None if 'get' finds nothing.
            - Error dictionary if any operation fails.
    \"\"\"
    print(f"--- TOOL DEBUG: run called with action={{action}}, page_id={{page_id}}", file=sys.stderr)
    local_args = locals()

    # --- Action: list ---
    if action == "list":
        query_params = {{}}
        for py_name, value in local_args.items():
            if py_name not in ["action", "page_id"] and value is not None and py_name in PARAM_MAP:
                original_prop_name = PARAM_MAP[py_name]
                query_params[original_prop_name] = value
        return _request("GET", params=query_params)

    # --- Action: get ---
    elif action == "get":
        if not page_id: return {{"error": "Validation Error", "message": "page_id is required for action 'get'."}}
        result = _request("GET", endpoint=f"/{{page_id}}")
        if isinstance(result, dict) and result.get("error") and result.get("status_code") == 404: return None
        return result

    # --- Action: create ---
    elif action == "create":
        payload = {{}}
        title_py_name = [k for k, v in PARAM_MAP.items() if v == TITLE_PROP_NAME][0]
        title_value = local_args.get(title_py_name)
        if title_value is None or str(title_value).strip() == "":
             return {{"error": "Validation Error", "message": f"'{{TITLE_PROP_NAME}}' property ('{{{{title_py_name}}}}' argument) is required for action 'create'."}}
        payload[TITLE_PROP_NAME] = title_value

        for py_name, value in local_args.items():
            if py_name not in ["action", "page_id", title_py_name] and value is not None and py_name in PARAM_MAP:
                original_prop_name = PARAM_MAP[py_name]
                payload[original_prop_name] = value
        return _request("POST", json=payload)

    # --- Action: update ---
    elif action == "update":
        if not page_id: return {{"error": "Validation Error", "message": "page_id is required for action 'update'."}}
        payload = {{}}
        update_provided = False
        for py_name, value in local_args.items():
             if py_name not in ["action", "page_id"] and py_name in PARAM_MAP:
                 original_prop_name = PARAM_MAP[py_name]
                 payload[original_prop_name] = value
                 update_provided = True

        if not update_provided: return {{"error": "Validation Error", "message": "At least one property value must be provided for action 'update'."}}
        return _request("PATCH", endpoint=f"/{{page_id}}", json=payload)

    # --- Action: delete ---
    elif action == "delete":
        if not page_id: return {{"error": "Validation Error", "message": "page_id is required for action 'delete'."}}
        return _request("DELETE", endpoint=f"/{{page_id}}")

    # --- Invalid Action ---
    else:
        valid_actions = ["list", "get", "create", "update", "delete"]
        return {{"error": "Validation Error", "message": f"Invalid action '{{action}}'. Must be one of {{valid_actions}}."}}

"""

    # --- Combine and Print Generated Code ---
    # Add shebang line at the very beginning
    full_generated_code = f"""{shebang}
# Generated Common Tool File for Notion Database: {DATABASE_NAME} ({SCHEMA['database_id']})
# Target Flask API Endpoint: {API_ENDPOINT_PATH}
# Use this file with sigoden/llm-functions by adding 'tools/{TOOL_NAME}.py' to tools.txt

{helper_code}

# --- Generated Tool Function ---
{run_function_code}

# --- End of Generated Code ---
"""
    print(full_generated_code.strip())
    print(f"\n--- Common tool file for '{DATABASE_NAME}' generated successfully. ---", file=sys.stderr)
    # Reverted number type hint change for now, let's see if shebang fixes it.
    # print(f"--- NOTE: Number types generated as Optional[str] due to parser limitations. ---", file=sys.stderr)
    print(f"--- Added #!/usr/bin/env python3 shebang line. ---", file=sys.stderr)
    print(f"--- Save this output to 'tools/{TOOL_NAME}.py' within your llm-functions directory ---", file=sys.stderr)
    print(f"--- and add 'tools/{TOOL_NAME}.py' to your tools.txt file. ---", file=sys.stderr)


