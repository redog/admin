# flask_api_generator.py
# Runs Flask API for one selected Notion DB. Fetches schema directly.
import os
import sys
import json
import argparse # Keep for port argument
from flask import Flask, request, jsonify
from notion_client import Client, APIResponseError
from datetime import date, datetime

# --- Notion Client Initialization (Moved earlier) ---
NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
if not NOTION_API_TOKEN:
    # Use print for startup errors before Flask logging is configured
    print("Error: Missing Notion API key. Set NOTION_API_TOKEN in your environment.", file=sys.stderr)
    exit(1)

try:
    notion = Client(auth=NOTION_API_TOKEN)
    print(" * Notion client initialized successfully.")
except Exception as e:
    print(f"Error: Failed to initialize Notion client: {e}", file=sys.stderr)
    exit(1)

# --- Functions ---

def fetch_databases():
    """Fetches accessible databases from Notion."""
    print(" * Fetching accessible databases from Notion...")
    try:
        all_databases = []
        start_cursor = None
        while True:
            response = notion.search(
                filter={"property": "object", "value": "database"},
                page_size=100,
                start_cursor=start_cursor
            )
            results = response.get("results", [])
            for db in results:
                if db.get("object") == "database" and db.get("title"):
                    title_list = db.get("title", [])
                    if title_list:
                        db_name = title_list[0].get("plain_text", "Untitled Database")
                        db_id = db.get("id")
                        if db_id:
                            all_databases.append({"name": db_name, "id": db_id})

            if response.get("has_more"):
                start_cursor = response.get("next_cursor")
            else:
                break
        print(f" * Found {len(all_databases)} databases.")
        return all_databases
    except APIResponseError as error:
         print(f"Error fetching databases from Notion: {error}", file=sys.stderr)
         return None
    except Exception as e:
        print(f"Error during database fetch: {e}", file=sys.stderr)
        return None

def display_databases_and_get_choice(databases):
    """Displays the list of databases and prompts the user for selection."""
    if not databases:
        print("Error: No databases found or accessible.", file=sys.stderr)
        return None

    print("\nSelect a Notion database to generate an API for:")
    for i, db in enumerate(databases):
        print(f"{i + 1}. {db.get('name', 'N/A')} (ID: {db.get('id', 'N/A')})")

    while True:
        # Print prompt immediately unbuffered
        print("Enter the number of the database: ", end="", flush=True)
        try:
            # Read input without prompt to avoid output into file redirection
            # May need to handle subsequent prints in this block as well.
            choice = input()
            index = int(choice) - 1
            if 0 <= index < len(databases):
                selected_db = databases[index]
                print(f" * You selected: {selected_db.get('name')} ({selected_db.get('id')})")
                return selected_db # Return the full dictionary
            else:
                print("Invalid selection. Please enter a number from the list.")
        except ValueError:
            print("\nInvalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            return None
        except EOFError:
             print("\nInput stream closed unexpectedly.")
             return None

def get_database_properties(database_id):
    """Retrieves the full properties schema for a given database ID."""
    print(f" * Retrieving schema for database ID: {database_id}...")
    try:
        database = notion.databases.retrieve(database_id=database_id)
        properties_schema = database.get('properties', {})
        print(" * Schema retrieved successfully.")
        return properties_schema
    except APIResponseError as error:
         print(f"Error retrieving schema for DB ID {database_id}: {error}", file=sys.stderr)
         return None
    except Exception as e:
        print(f"Error retrieving properties for DB ID {database_id}: {e}", file=sys.stderr)
        return None

# --- Schema Selection Logic (at script start) ---
SCHEMA = None
selected_db_info = None

available_databases = fetch_databases()

if available_databases:
    # Prompt user for choice
    selected_db_info = display_databases_and_get_choice(available_databases)

    if selected_db_info:
        # Fetch the schema for the chosen DB
        properties = get_database_properties(selected_db_info["id"])
        if properties is not None:
            # Construct the SCHEMA dictionary needed by the rest of the script
            SCHEMA = {
                "database_id": selected_db_info["id"],
                "database_name": selected_db_info["name"],
                "properties": properties
            }
        else:
            print(f"Error: Failed to retrieve schema for database '{selected_db_info['name']}'.", file=sys.stderr)
    else:
        # User cancelled selection
        print("No database selected. Exiting.", file=sys.stderr)
else:
    # Failed to fetch database list
     print("Could not retrieve database list. Exiting.", file=sys.stderr)


# Exit if schema could not be obtained
if not SCHEMA:
    print("Exiting due to inability to obtain database schema.", file=sys.stderr)
    exit(1)

# --- Configuration (using selected SCHEMA) ---
DB_ID = SCHEMA['database_id']
# Sanitize DB name for slug more robustly
DB_NAME_SLUG = re.sub(r'[^\w]+', '_', SCHEMA['database_name'].lower()).strip('_')
if not DB_NAME_SLUG: DB_NAME_SLUG = DB_ID.replace('-','_') # Fallback if name is only symbols

PROPERTIES_SCHEMA = SCHEMA['properties'] # Reference the properties dictionary

# --- Notion API Interaction Helpers (with Schema Awareness) ---

def build_notion_filter(query_params: dict) -> dict | None:
    """
    Translates Flask query parameters into a Notion API filter structure,
    using the loaded PROPERTIES_SCHEMA. Handles case-insensitivity for param names.
    """
    if not query_params:
        return None

    filter_conditions = []
    # Create a lower-case mapping of schema properties for case-insensitive lookup
    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for param_name_lower, param_value in query_params.items():
        param_name_lower = param_name_lower.lower() # Ensure input param is lower case
        # Find the original schema property name
        matched_prop_name = schema_props_lower.get(param_name_lower)

        if not matched_prop_name:
            app.logger.warning(f"Query parameter '{param_name_lower}' not found in schema, skipping filter.")
            continue

        prop_schema = PROPERTIES_SCHEMA[matched_prop_name]
        prop_type = prop_schema['type']
        prop_api_name = matched_prop_name # Use original case name for Notion API

        condition = None
        try:
            # Build filter condition based on type
            if prop_type in ['rich_text', 'title', 'email', 'phone_number', 'url']:
                condition = {"property": prop_api_name, prop_type: {"equals": param_value}}
            elif prop_type == 'number':
                condition = {"property": prop_api_name, "number": {"equals": float(param_value)}}
            elif prop_type == 'select':
                condition = {"property": prop_api_name, "select": {"equals": param_value}}
            elif prop_type == 'multi_select':
                 condition = {"property": prop_api_name, "multi_select": {"contains": param_value}}
            elif prop_type == 'checkbox':
                 condition = {"property": prop_api_name, "checkbox": {"equals": param_value.lower() == 'true'}}
            elif prop_type == 'date':
                 condition = {"property": prop_api_name, "date": {"equals": param_value}} # Assumes YYYY-MM-DD
            elif prop_type == 'status':
                 condition = {"property": prop_api_name, "status": {"equals": param_value}}
            # Add more complex types: people (contains user ID), relation (contains page ID)
            elif prop_type == 'people':
                 condition = {"property": prop_api_name, "people": {"contains": param_value}} # Assumes value is user ID
            elif prop_type == 'relation':
                 condition = {"property": prop_api_name, "relation": {"contains": param_value}} # Assumes value is page ID

            if condition:
                filter_conditions.append(condition)
            else:
                 app.logger.warning(f"Filtering not implemented for type '{prop_type}' (property: '{prop_api_name}')")

        except ValueError:
             app.logger.warning(f"Could not convert value '{param_value}' for property '{prop_api_name}' (type: {prop_type}), skipping filter.")
        except Exception as e:
             app.logger.error(f"Error building filter for {prop_api_name}: {e}, skipping.")

    if not filter_conditions:
        return None
    elif len(filter_conditions) == 1:
        return filter_conditions[0]
    else:
        return {"and": filter_conditions}


def build_notion_properties_payload(data: dict) -> dict:
    """
    Translates incoming JSON data into the Notion API properties payload format.
    Handles case-insensitivity for input data keys.
    """
    properties_payload = {}
    # Create a lower-case mapping of schema properties for case-insensitive lookup
    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for input_key, value in data.items():
        input_key_lower = input_key.lower()
        # Find the original schema property name
        matched_prop_name = schema_props_lower.get(input_key_lower)

        if not matched_prop_name:
            app.logger.warning(f"Property '{input_key}' not found in schema, skipping.")
            continue

        prop_schema = PROPERTIES_SCHEMA[matched_prop_name]
        prop_type = prop_schema['type']
        prop_api_name = matched_prop_name # Use original case name for Notion API

        payload_value = None
        try:
            # Handle null values explicitly to clear fields
            if value is None:
                if prop_type == 'select': payload_value = {"select": None}
                elif prop_type == 'multi_select': payload_value = {"multi_select": []}
                elif prop_type == 'date': payload_value = {"date": None}
                elif prop_type == 'people': payload_value = {"people": []}
                elif prop_type == 'relation': payload_value = {"relation": []}
                elif prop_type in ['rich_text', 'title']: payload_value = {prop_type: []}
                elif prop_type == 'number': payload_value = {"number": None}
                elif prop_type == 'email': payload_value = {"email": None}
                elif prop_type == 'phone_number': payload_value = {"phone_number": None}
                elif prop_type == 'url': payload_value = {"url": None}
                # Cannot set checkbox to null, skip if value is None
                elif prop_type == 'checkbox': continue
                # Status might not be clearable with None, depends on Notion API version
                elif prop_type == 'status': continue # Or {"status": None}? Needs testing.
                else: continue # Skip unknown types or types that can't be null

            # Process non-null values
            elif prop_type == 'title':
                payload_value = {"title": [{"type": "text", "text": {"content": str(value)}}]}
            elif prop_type == 'rich_text':
                 payload_value = {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}
            elif prop_type == 'number':
                 payload_value = {"number": float(value) if value != "" else None}
            elif prop_type == 'select':
                 payload_value = {"select": {"name": str(value)}} # Assumes name exists
            elif prop_type == 'multi_select':
                 # Expects a list of names
                 if isinstance(value, list):
                     payload_value = {"multi_select": [{"name": str(item)} for item in value]}
                 else: # Handle single string value? Assume it's a list with one item.
                     payload_value = {"multi_select": [{"name": str(value)}]}
            elif prop_type == 'date':
                 payload_value = {"date": {"start": str(value)}} # Assumes YYYY-MM-DD
            elif prop_type == 'email':
                 payload_value = {"email": str(value)}
            elif prop_type == 'phone_number':
                  payload_value = {"phone_number": str(value)}
            elif prop_type == 'checkbox':
                  payload_value = {"checkbox": bool(value)}
            elif prop_type == 'url':
                  payload_value = {"url": str(value)}
            elif prop_type == 'status':
                  payload_value = {"status": {"name": str(value)}} # Assumes name exists
            # Add more complex types like people/relation (expecting list of IDs)
            elif prop_type == 'people':
                 if isinstance(value, list):
                      payload_value = {"people": [{"id": str(user_id)} for user_id in value]}
                 else: # Assume single ID
                      payload_value = {"people": [{"id": str(value)}]}
            elif prop_type == 'relation':
                 if isinstance(value, list):
                      payload_value = {"relation": [{"id": str(page_id)} for page_id in value]}
                 else: # Assume single ID
                      payload_value = {"relation": [{"id": str(value)}]}

            # Only add if a valid payload value was generated
            if payload_value is not None:
                 properties_payload[prop_api_name] = payload_value
            elif value is not None: # Log warning only if input value wasn't None
                 app.logger.warning(f"Payload generation not implemented or failed for type '{prop_type}' (property: '{prop_api_name}')")

        except (ValueError, TypeError) as e:
             app.logger.warning(f"Could not format value '{value}' for property '{prop_api_name}' (type: {prop_type}): {e}, skipping.")
        except Exception as e:
            app.logger.error(f"Error building payload for {prop_api_name}: {e}, skipping.")

    return properties_payload


def simplify_notion_page(page: dict) -> dict:
    """
    Simplifies the complex Notion page object structure into a flatter dictionary.
    """
    simplified = {"page_id": page.get("id")}
    properties = page.get("properties", {})
    for prop_name, prop_data in properties.items():
        prop_type = prop_data.get("type")
        value = None
        try:
            # Extract values based on type
            if prop_type == 'title':
                value = prop_data['title'][0]['plain_text'] if prop_data.get('title') else None
            elif prop_type == 'rich_text':
                 value = prop_data['rich_text'][0]['plain_text'] if prop_data.get('rich_text') else None
            elif prop_type == 'number':
                 value = prop_data.get('number')
            elif prop_type == 'select':
                 value = prop_data['select']['name'] if prop_data.get('select') else None
            elif prop_type == 'multi_select':
                 value = [opt['name'] for opt in prop_data.get('multi_select', [])]
            elif prop_type == 'date':
                 value = prop_data['date']['start'] if prop_data.get('date') else None
            elif prop_type == 'people':
                 value = [person.get('name', person.get('id')) for person in prop_data.get('people', []) if person]
            elif prop_type == 'files':
                 value = [file_obj.get('name') for file_obj in prop_data.get('files', [])]
            elif prop_type == 'checkbox':
                 value = prop_data.get('checkbox')
            elif prop_type == 'url':
                 value = prop_data.get('url')
            elif prop_type == 'email':
                 value = prop_data.get('email')
            elif prop_type == 'phone_number':
                 value = prop_data.get('phone_number')
            elif prop_type == 'formula':
                 formula_result = prop_data.get('formula', {})
                 result_type = formula_result.get('type')
                 if result_type in ['string', 'number', 'boolean', 'date']: value = formula_result.get(result_type)
                 else: value = f"Formula result type: {result_type}" # Placeholder
            elif prop_type == 'relation':
                 value = [relation.get('id') for relation in prop_data.get('relation', [])]
            elif prop_type == 'rollup':
                 rollup_result = prop_data.get('rollup', {})
                 result_type = rollup_result.get('type')
                 if result_type in ['number', 'date']: value = rollup_result.get(result_type)
                 elif result_type == 'array': value = rollup_result.get('array')
                 else: value = f"Rollup type '{result_type}'"
            elif prop_type == 'created_time': value = prop_data.get('created_time')
            elif prop_type == 'last_edited_time': value = prop_data.get('last_edited_time')
            elif prop_type == 'created_by': value = {"id": prop_data.get('created_by', {}).get('id')}
            elif prop_type == 'last_edited_by': value = {"id": prop_data.get('last_edited_by', {}).get('id')}
            elif prop_type == 'status': value = prop_data['status']['name'] if prop_data.get('status') else None

            simplified[prop_name] = value

        except (KeyError, IndexError, TypeError) as e:
            app.logger.error(f"Error simplifying property '{prop_name}' (type: {prop_type}): {e}")
            simplified[prop_name] = f"Error processing type '{prop_type}'"

    return simplified


# --- Flask App Initialization ---
# Ensure Flask is imported
import re # Import re for slugifying
from flask import Flask, request, jsonify
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False # Keep JSON order as is

# --- API Endpoints ---
api_base = f"/api/{DB_NAME_SLUG}"
print(f" * Registering API endpoints for '{SCHEMA['database_name']}' at {api_base}")

@app.route(api_base, methods=['GET'])
def list_items():
    """Retrieves a list of items (pages) from the Notion database."""
    query_params = request.args.to_dict()
    notion_filter = build_notion_filter(query_params)
    app.logger.info(f"Executing Query on DB: {DB_ID}")
    app.logger.info(f"Filters received: {query_params}")
    app.logger.debug(f"Notion filter generated: {json.dumps(notion_filter, indent=2)}")
    try:
        all_results = []
        start_cursor = None
        while True:
            query_kwargs = {"database_id": DB_ID, "start_cursor": start_cursor, "page_size": 100}
            if notion_filter is not None: query_kwargs["filter"] = notion_filter
            response = notion.databases.query(**query_kwargs)
            results = response.get("results", [])
            all_results.extend(results)
            if response.get("has_more"): start_cursor = response.get("next_cursor")
            else: break
        simplified_results = [simplify_notion_page(page) for page in all_results]
        return jsonify(simplified_results)
    except APIResponseError as error:
        app.logger.error(f"Notion API Error during list_items: {error}")
        error_body = getattr(error, 'body', {})
        message = error_body.get('message', str(error)) if isinstance(error_body, dict) else str(error)
        return jsonify({"error": f"Notion API Error: {error.code}", "message": message}), getattr(error, "status", 500)
    except Exception as e:
        app.logger.error(f"Server Error during list_items: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred", "message": str(e)}), 500

@app.route(f"{api_base}/<page_id>", methods=['GET'])
def get_item(page_id):
    """Retrieves a specific item (page) by its Notion Page ID."""
    app.logger.info(f"Retrieving page: {page_id}")
    try:
        page = notion.pages.retrieve(page_id=page_id)
        simplified_page = simplify_notion_page(page)
        return jsonify(simplified_page)
    except APIResponseError as error:
        if error.status == 404:
             app.logger.info(f"Page not found: {page_id}")
             return jsonify({"error": "Not Found", "message": f"Item with ID {page_id} not found."}), 404
        else:
            app.logger.error(f"Notion API Error during get_item ({page_id}): {error}")
            return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), getattr(error, "status", 500)
    except Exception as e:
        app.logger.error(f"Server Error during get_item ({page_id}): {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred", "message": str(e)}), 500

@app.route(api_base, methods=['POST'])
def create_item():
    """Creates a new item (page) in the Notion database."""
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400
    data = request.get_json()
    app.logger.info(f"Received data for creation: {data}")
    properties_payload = build_notion_properties_payload(data)
    if not properties_payload:
         if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}), 400
         else: return jsonify({"error": "Bad Request", "message": "No valid properties provided or failed to build payload."}), 400
    app.logger.debug(f"Notion properties payload for create: {json.dumps(properties_payload, indent=2)}")
    try:
        new_page = notion.pages.create(parent={"database_id": DB_ID}, properties=properties_payload)
        simplified_page = simplify_notion_page(new_page)
        app.logger.info(f"Successfully created page: {simplified_page.get('page_id')}")
        return jsonify(simplified_page), 201
    except APIResponseError as error:
        app.logger.error(f"Notion API Error during create_item: {error}")
        error_body = getattr(error, 'body', {})
        message = error_body.get('message', str(error)) if isinstance(error_body, dict) else str(error)
        return jsonify({"error": f"Notion API Error: {error.code}", "message": message}), getattr(error, "status", 500)
    except Exception as e:
        app.logger.error(f"Server Error during create_item: {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred", "message": str(e)}), 500

@app.route(f"{api_base}/<page_id>", methods=['PUT', 'PATCH'])
def update_item(page_id):
    """Updates an existing item (page) by its Notion Page ID."""
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400
    data = request.get_json()
    app.logger.info(f"Received data for update on {page_id}: {data}")
    properties_payload = build_notion_properties_payload(data)
    if not properties_payload:
         if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}), 400
         else: return jsonify({"error": "Bad Request", "message": "No valid properties provided or failed to build payload."}), 400
    app.logger.debug(f"Notion properties payload for update ({page_id}): {json.dumps(properties_payload, indent=2)}")
    try:
        updated_page = notion.pages.update(page_id=page_id, properties=properties_payload)
        simplified_page = simplify_notion_page(updated_page)
        app.logger.info(f"Successfully updated page: {page_id}")
        return jsonify(simplified_page)
    except APIResponseError as error:
        if error.status == 404:
             app.logger.info(f"Page not found for update: {page_id}")
             return jsonify({"error": "Not Found", "message": f"Item with ID {page_id} not found."}), 404
        else:
            app.logger.error(f"Notion API Error during update_item ({page_id}): {error}")
            error_body = getattr(error, 'body', {})
            message = error_body.get('message', str(error)) if isinstance(error_body, dict) else str(error)
            return jsonify({"error": f"Notion API Error: {error.code}", "message": message}), getattr(error, "status", 500)
    except Exception as e:
        app.logger.error(f"Server Error during update_item ({page_id}): {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred", "message": str(e)}), 500

@app.route(f"{api_base}/<page_id>", methods=['DELETE'])
def delete_item(page_id):
    """Deletes (archives) an item (page) by its Notion Page ID."""
    app.logger.info(f"Archiving page: {page_id}")
    try:
        notion.pages.update(page_id=page_id, archived=True)
        app.logger.info(f"Successfully archived page: {page_id}")
        return jsonify({"message": f"Item {page_id} archived successfully."}), 200
    except APIResponseError as error:
        if error.status == 404:
             app.logger.info(f"Page not found for delete (archive): {page_id}")
             return jsonify({"error": "Not Found", "message": f"Item with ID {page_id} not found."}), 404
        else:
            app.logger.error(f"Notion API Error during delete_item ({page_id}): {error}")
            return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), getattr(error, "status", 500)
    except Exception as e:
        app.logger.error(f"Server Error during delete_item ({page_id}): {e}", exc_info=True)
        return jsonify({"error": "An internal server error occurred", "message": str(e)}), 500


# --- Argument Parser for Port ---
parser = argparse.ArgumentParser(description="Flask API Server for a selected Notion Database")
parser.add_argument(
    "-p", "--port",
    type=int,
    default=5002, # Default port
    help="Port number to run the Flask server on."
)
# Only parse known args to avoid conflicts if Flask/Werkzeug add their own
cli_args, _ = parser.parse_known_args()


# --- Run Flask App ---
if __name__ == '__main__':
    if not SCHEMA:
        pass # Error already printed
    else:
        port = cli_args.port
        print(f" --- Starting Flask server for '{SCHEMA['database_name']}' on port {port} --- ")
        # Use reloader=False to prevent startup logic running twice in debug mode
        # Set debug=False for production or if startup logic causes issues
        app.run(debug=True, port=port, use_reloader=False)

