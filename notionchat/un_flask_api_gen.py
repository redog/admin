# flask_api_generator.py
# Runs Flask API for one selected Notion DB. Fetches schema using ultimate-notion with Session context.
import os
import re
import sys
import json
import argparse
from flask import Flask, request, jsonify
from datetime import date, datetime # date & datetime used for type hints and by ultimate-notion
import atexit # For graceful shutdown
from pendulum import datetime as pendulum_datetime # For date handling

# --- Ultimate Notion Client Initialization ---
from ultimate_notion import Session, Page, Database, User # Core objects
from ultimate_notion.props import PropertyValue # Base PropertyValue class
from ultimate_notion.rich_text import RichText

# --- Global Variables ---
# These will be initialized after the Notion session starts and DB is selected.
db_obj: Database | None = None
SCHEMA_DICT: dict | None = None
PROPERTIES_SCHEMA: dict | None = None # This is db_obj.schema_dict() essentially
DB_ID: str | None = None
DB_NAME_SLUG: str | None = None

# This will hold the active ultimate-notion session.
# Made global to be easily accessible by Flask route handlers.
active_notion_session: Session | None = None

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# --- Functions ---

def fetch_databases_un(notion_ses: Session): # Accepts session
    """Fetches accessible databases from Notion using ultimate-notion."""
    print(" * Fetching accessible databases from Notion (using ultimate-notion Session)...")
    try:
        # Search for databases. ultimate-notion's search_db returns a generator.
        all_db_objects = list(notion_ses.search_db())
        all_databases = []
        for db_item in all_db_objects:
            if isinstance(db_item, Database):
                db_id = str(db_item.id)
                db_name = "Untitled Database" # Default name
                # Safely get the database title
                if db_item.title:
                    if isinstance(db_item.title, RichText):
                        db_name = db_item.title.plain_text
                    elif hasattr(db_item.title, 'plain_text'):
                        db_name = db_item.title.plain_text
                    else:
                        db_name = str(db_item.title)
                all_databases.append({"name": db_name, "id": db_id})

        print(f" * Found {len(all_databases)} databases.")
        return all_databases
    except Exception as e:
        print(f"Error during database fetch: {e}", file=sys.stderr)
        return None

def display_databases_and_get_choice(databases):
    """Displays the list of databases and prompts the user for selection."""
    if not databases:
        print("Error: No databases found or accessible.", file=sys.stderr)
        return None

    print("\nSelect a Notion database to generate an API for:")
    for i, db_data in enumerate(databases):
        print(f"{i + 1}. {db_data.get('name', 'N/A')} (ID: {db_data.get('id', 'N/A')})")

    while True:
        print("Enter the number of the database: ", end="", flush=True)
        try:
            choice_str = input()
            index = int(choice_str) - 1
            if 0 <= index < len(databases):
                selected_db_data = databases[index]
                print(f" * You selected: {selected_db_data.get('name')} ({selected_db_data.get('id')})")
                return selected_db_data
            else:
                print("Invalid selection. Please enter a number from the list.")
        except ValueError:
            print("\nInvalid input. Please enter a number.")
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
            return None
        except EOFError: # Handle cases where input stream is closed (e.g., piping)
            print("\nInput stream closed unexpectedly. No database selected.")
            return None

def get_database_properties_un(notion_ses: Session, database_id: str):
    """Retrieves the properties schema for a given database ID using ultimate-notion."""
    global db_obj # Allow modification of the global db_obj
    print(f" * Retrieving schema for database ID: {database_id} (using ultimate-notion Session)...")
    try:
        # Get the Database object using the session
        db_obj = notion_ses.get_db(database_id)
        if db_obj.is_empty:
            print(f"Error: Database with ID {database_id} is empty.", file=sys.stderr)
            return None

        # Get the schema from the Database object's properties
        properties_schema = {}
        for prop_name in dir(db_obj.schema):
            if not prop_name.startswith('_'):  # Skip private attributes
                prop = getattr(db_obj.schema, prop_name)
                if hasattr(prop, 'type'):
                    # Convert any non-serializable objects to strings
                    prop_type = str(prop.type)
                    properties_schema[prop_name] = {
                        "type": prop_type,
                        "name": prop_name
                    }
        print(" * Schema retrieved successfully.")
        return properties_schema
    except Exception as e:
        print(f"Error retrieving properties for DB ID {database_id}: {e}", file=sys.stderr)
        return None

def build_notion_filter_un(query_params: dict) -> dict | None:
    """
    Translates Flask query parameters into a Notion filter object.
    Uses global PROPERTIES_SCHEMA.
    """
    if not query_params or not PROPERTIES_SCHEMA:
        return None

    filter_conditions = []
    # Create a case-insensitive mapping from lowercased param name to actual schema property name
    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for param_name_query, param_value in query_params.items():
        # Normalize query parameter name to lowercase for matching
        param_name_lower = param_name_query.lower()
        
        # Skip pagination parameters if they are passed in query_params for filtering
        if param_name_lower in ['page_size', 'start_cursor']:
            continue

        matched_prop_name = schema_props_lower.get(param_name_lower)

        if not matched_prop_name:
            app.logger.warning(f"Query parameter '{param_name_query}' (as '{param_name_lower}') not found in schema, skipping filter.")
            continue

        prop_schema_dict = PROPERTIES_SCHEMA[matched_prop_name]
        prop_type = prop_schema_dict['type']

        try:
            # Create filter condition based on property type
            if prop_type in ['rich_text', 'title', 'email', 'phone_number', 'url']:
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": param_value
                })
            elif prop_type == 'number':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": float(param_value)
                })
            elif prop_type == 'select':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": param_value
                })
            elif prop_type == 'multi_select':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "contains": param_value
                })
            elif prop_type == 'checkbox':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": param_value.lower() == 'true'
                })
            elif prop_type == 'date':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": param_value
                })
            elif prop_type == 'status':
                filter_conditions.append({
                    "property": matched_prop_name,
                    "equals": param_value
                })
            elif prop_type in ['people', 'relation']:
                filter_conditions.append({
                    "property": matched_prop_name,
                    "contains": param_value
                })

        except ValueError:
            app.logger.warning(f"Could not convert value '{param_value}' for property '{matched_prop_name}' (type: {prop_type}), skipping filter.")
        except Exception as e:
            app.logger.error(f"Error building filter for {matched_prop_name}: {e}, skipping.")

    if not filter_conditions:
        return None
    
    # Return single condition or a compound 'AND' filter for multiple conditions
    return filter_conditions[0] if len(filter_conditions) == 1 else {
        "and": filter_conditions
    }

def build_notion_properties_payload_un(data: dict) -> dict:
    """
    Translates incoming JSON data into a dictionary suitable for ultimate-notion's
    create_page kwargs or page.set_prop_value. Uses global PROPERTIES_SCHEMA.
    """
    properties_payload = {}
    if not PROPERTIES_SCHEMA:
        return properties_payload

    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for input_key, value in data.items():
        input_key_lower = input_key.lower()
        matched_prop_name = schema_props_lower.get(input_key_lower)

        if not matched_prop_name:
            app.logger.warning(f"Property '{input_key}' (as '{input_key_lower}') not found in schema, skipping.")
            continue

        prop_schema_dict = PROPERTIES_SCHEMA[matched_prop_name]
        prop_type = prop_schema_dict['type']

        try:
            if value is None:
                if prop_type not in ['checkbox']:
                    properties_payload[matched_prop_name] = None
                elif prop_type == 'checkbox':
                    properties_payload[matched_prop_name] = False
                continue

            # Process non-null values based on expected types
            if prop_type in ['title', 'rich_text', 'email', 'phone_number', 'url', 'select', 'status']:
                properties_payload[matched_prop_name] = str(value)
            elif prop_type == 'number':
                properties_payload[matched_prop_name] = float(value) if value != "" and value is not None else None
            elif prop_type == 'multi_select':
                if isinstance(value, list):
                    properties_payload[matched_prop_name] = [str(item) for item in value]
                elif value is not None:
                    properties_payload[matched_prop_name] = [str(value)]
                else:
                    properties_payload[matched_prop_name] = []
            elif prop_type == 'date':
                properties_payload[matched_prop_name] = value
            elif prop_type == 'checkbox':
                properties_payload[matched_prop_name] = bool(value)
            elif prop_type in ['people', 'relation']:
                if isinstance(value, list):
                    properties_payload[matched_prop_name] = [str(item_id) for item_id in value]
                elif value is not None:
                    properties_payload[matched_prop_name] = [str(value)]
                else:
                    properties_payload[matched_prop_name] = []
            else:
                app.logger.warning(f"Payload generation for type '{prop_type}' (prop: '{matched_prop_name}') using direct value.")
                properties_payload[matched_prop_name] = value

        except (ValueError, TypeError) as e:
            app.logger.warning(f"Could not format value '{value}' for property '{matched_prop_name}' (type: {prop_type}): {e}, skipping.")
        except Exception as e:
            app.logger.error(f"Error building payload for {matched_prop_name}: {e}, skipping.")

    return properties_payload

def simplify_notion_page_un(page: Page) -> dict:
    """
    Simplifies an ultimate-notion Page object into a flatter dictionary for JSON response.
    Uses global PROPERTIES_SCHEMA and db_obj.
    """
    simplified = {
        "page_id": str(page.id),
        "page_url": page.url,
        "archived": page.archived if hasattr(page, 'archived') else False,
        "last_edited_time": page.last_edited_time.isoformat() if page.last_edited_time else None,
        "created_time": page.created_time.isoformat() if page.created_time else None
    }

    if not PROPERTIES_SCHEMA or db_obj is None:
        app.logger.error("PROPERTIES_SCHEMA or db_obj not available for page simplification.")
        return simplified

    # Get the schema from the database
    schema = db_obj.schema

    for prop_name, prop_schema_details in PROPERTIES_SCHEMA.items():
        prop_api_type = prop_schema_details['type']
        ui_value = None

        try:
            # Try to get the property from page.props
            if hasattr(page, 'props'):
                prop_value_obj = getattr(page.props, prop_name, None)
            else:
                prop_value_obj = None

            if prop_value_obj is None:
                ui_value = None
            else:
                # For most properties, the value is directly accessible
                if prop_api_type in ['title', 'rich_text', 'Text']:
                    if hasattr(prop_value_obj, 'plain_text'):
                        ui_value = prop_value_obj.plain_text
                    elif hasattr(prop_value_obj, 'value'):
                        if hasattr(prop_value_obj.value, 'plain_text'):
                            ui_value = prop_value_obj.value.plain_text
                        else:
                            ui_value = str(prop_value_obj.value)
                    elif hasattr(prop_value_obj, 'text'):
                        ui_value = prop_value_obj.text
                    else:
                        ui_value = str(prop_value_obj)
                elif prop_api_type == 'number':
                    if hasattr(prop_value_obj, 'value'):
                        ui_value = float(prop_value_obj.value) if prop_value_obj.value is not None else None
                    else:
                        ui_value = float(prop_value_obj) if prop_value_obj is not None else None
                elif prop_api_type in ['select', 'status']:
                    if hasattr(prop_value_obj, 'name'):
                        ui_value = str(prop_value_obj.name)
                    elif hasattr(prop_value_obj, 'value'):
                        ui_value = str(prop_value_obj.value)
                    else:
                        ui_value = str(prop_value_obj)
                elif prop_api_type == 'multi_select':
                    if hasattr(prop_value_obj, '__iter__'):
                        ui_value = [str(opt.name if hasattr(opt, 'name') else opt) for opt in prop_value_obj]
                    else:
                        ui_value = [str(prop_value_obj)]
                elif prop_api_type == 'date':
                    if hasattr(prop_value_obj, 'start') and hasattr(prop_value_obj, 'end'):
                        ui_value = {
                            "start": prop_value_obj.start.isoformat() if prop_value_obj.start else None,
                            "end": prop_value_obj.end.isoformat() if prop_value_obj.end else None,
                            "time_zone": str(prop_value_obj.time_zone) if hasattr(prop_value_obj, 'time_zone') else None
                        }
                    elif hasattr(prop_value_obj, 'value'):
                        ui_value = str(prop_value_obj.value)
                    else:
                        ui_value = str(prop_value_obj)
                elif prop_api_type == 'people':
                    if hasattr(prop_value_obj, '__iter__'):
                        ui_value = [{"id": str(user.id), "name": str(user.name if hasattr(user, 'name') else None), "type": "user"} 
                                  for user in prop_value_obj if isinstance(user, User)]
                    else:
                        ui_value = [{"id": str(prop_value_obj.id), "name": str(prop_value_obj.name if hasattr(prop_value_obj, 'name') else None), "type": "user"}]
                elif prop_api_type == 'relation':
                    related_pages_info = []
                    if hasattr(prop_value_obj, '__iter__'):
                        pages_to_process = prop_value_obj
                    else:
                        pages_to_process = [prop_value_obj]
                        
                    for p_stub in pages_to_process:
                        if isinstance(p_stub, Page):
                            page_info = {"id": str(p_stub.id)}
                            try:
                                if p_stub.title and p_stub.title.value:
                                    page_info["title"] = str(p_stub.title.value.plain_text)
                                elif hasattr(p_stub, 'is_deleted') and p_stub.is_deleted():
                                    page_info["title"] = "Untitled (Deleted Relation)"
                                else:
                                    page_info["title"] = "Untitled Relation"
                            except Exception as rel_title_ex:
                                app.logger.warning(f"Could not get title for related page {p_stub.id}: {rel_title_ex}")
                                page_info["title"] = "Error fetching title"
                            related_pages_info.append(page_info)
                    ui_value = related_pages_info
                elif prop_api_type == 'files':
                    if hasattr(prop_value_obj, '__iter__'):
                        ui_value = [{"name": str(f.name), "url": str(f.url if hasattr(f, 'url') else (f.external_url if hasattr(f, 'external_url') else None))} 
                                  for f in prop_value_obj if hasattr(f, 'name')]
                    else:
                        ui_value = [{"name": str(prop_value_obj.name), "url": str(prop_value_obj.url if hasattr(prop_value_obj, 'url') else None)}]
                elif prop_api_type == 'checkbox':
                    if hasattr(prop_value_obj, 'value'):
                        ui_value = bool(prop_value_obj.value)
                    else:
                        ui_value = bool(prop_value_obj)
                elif prop_api_type in ['url', 'email', 'phone_number']:
                    if hasattr(prop_value_obj, 'value'):
                        ui_value = str(prop_value_obj.value)
                    elif hasattr(prop_value_obj, 'url'):
                        ui_value = str(prop_value_obj.url)
                    else:
                        ui_value = str(prop_value_obj)
                else:
                    # For any other type, try to get the value in a safe way
                    if hasattr(prop_value_obj, 'value'):
                        ui_value = str(prop_value_obj.value)
                    elif hasattr(prop_value_obj, 'plain_text'):
                        ui_value = str(prop_value_obj.plain_text)
                    elif hasattr(prop_value_obj, 'text'):
                        ui_value = str(prop_value_obj.text)
                    else:
                        ui_value = str(prop_value_obj)

            simplified[prop_name] = ui_value

        except Exception as e:
            app.logger.error(f"Error simplifying property '{prop_name}' (API type: {prop_api_type}) for page {page.id}: {e}", exc_info=True)
            simplified[prop_name] = f"Error processing property '{prop_name}': {str(e)}"

    return simplified

# --- Flask App Route Definitions ---

def list_items():
    global db_obj, DB_ID
    if not DB_ID:
        return jsonify({"error": "Database ID missing"}), 500
    if db_obj is None:
        return jsonify({"error": "Database object not initialized"}), 500
    if db_obj.is_empty:
        return jsonify({"error": "Database is empty"}), 500

    query_params = request.args.to_dict()
    notion_filter_obj = build_notion_filter_un(query_params) 

    app.logger.info(f"Executing Query on DB: {DB_ID}")
    app.logger.info(f"Filters received: {request.args.to_dict()}") 
    if notion_filter_obj: app.logger.debug(f"Ultimate Notion filter object: {notion_filter_obj}")

    try:
        query_builder = db_obj.query
        if notion_filter_obj:
            query_builder = query_builder.filter(notion_filter_obj)

        page_size_str = query_params.get('page_size')
        start_cursor_str = query_params.get('start_cursor')

        if page_size_str:
            try:
                query_builder = query_builder.page_size(int(page_size_str))
            except ValueError:
                app.logger.warning(f"Invalid page_size: {page_size_str}. Using default.")
        if start_cursor_str:
            query_builder = query_builder.start_cursor(start_cursor_str)
        
        all_page_objects = list(query_builder.execute()) 
        
        simplified_results = [simplify_notion_page_un(page_obj) for page_obj in all_page_objects]
        
        return jsonify(simplified_results)
    except Exception as e:
        app.logger.error(f"Server Error (list_items): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def get_item(page_id_str):
    global active_notion_session
    if not active_notion_session:
        return jsonify({"error": "Notion session not active"}), 500

    app.logger.info(f"Retrieving page: {page_id_str}")
    try:
        page_obj = active_notion_session.get_page(page_id_str)
        if not page_obj: 
             return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404
        simplified_page = simplify_notion_page_un(page_obj)
        return jsonify(simplified_page)
    except Exception as e:
        app.logger.error(f"Server Error (get_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def create_item():
    global db_obj, active_notion_session
    if not db_obj or not active_notion_session:
        return jsonify({"error": "Database or session not initialized"}), 500
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400

    data = request.get_json()
    app.logger.info(f"Received data for creation: {data}")
    
    if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}), 400
    
    properties_for_un = build_notion_properties_payload_un(data)

    if not properties_for_un and data : 
        app.logger.warning(f"No valid properties derived from input: {data}")
        return jsonify({"error": "Bad Request", "message": "No valid properties found in payload to create or update page."}), 400

    app.logger.debug(f"Payload for create: {json.dumps(properties_for_un, indent=2, default=str)}")

    try:
        title_prop_name = db_obj.title_prop_name 
        
        if title_prop_name not in properties_for_un and db_obj.schema.get_prop(title_prop_name).mandatory: 
             app.logger.warning(f"Title property '{title_prop_name}' not found in payload. Notion may require it.")

        new_page_obj = db_obj.create_page(**properties_for_un)
        
        simplified_page = simplify_notion_page_un(new_page_obj)
        app.logger.info(f"Successfully created page: {new_page_obj.id}")
        return jsonify(simplified_page), 201
    except Exception as e:
        app.logger.error(f"Server Error (create_item): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def update_item(page_id_str):
    global active_notion_session, db_obj
    if not active_notion_session or not db_obj:
        return jsonify({"error": "Notion session or DB object not active"}), 500
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400

    data = request.get_json()
    app.logger.info(f"Data for update ({page_id_str}): {data}")
    
    if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}), 400

    properties_to_update = build_notion_properties_payload_un(data)

    if not properties_to_update and data:
        app.logger.warning(f"No valid properties derived from input for update: {data}")
        return jsonify({"error": "Bad Request", "message": "No valid properties found in payload for update."}), 400

    app.logger.debug(f"Payload for update ({page_id_str}): {json.dumps(properties_to_update, indent=2, default=str)}")

    try:
        page_obj = active_notion_session.get_page(page_id_str)
        if not page_obj: 
            return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404

        title_prop_name = db_obj.title_prop_name
        changed = False
        for prop_name, value in properties_to_update.items():
            if prop_name == title_prop_name:
                if page_obj.title.value.plain_text != value : 
                    page_obj.title = value 
                    changed = True
            else:
                page_obj.set_prop_value(prop_name, value)
                changed = True 

        if changed:
            page_obj.update() 
            app.logger.info(f"Successfully updated page: {page_id_str}")
        else:
            app.logger.info(f"No changes detected for page: {page_id_str}")

        simplified_page = simplify_notion_page_un(page_obj) 
        return jsonify(simplified_page)
    except Exception as e:
        app.logger.error(f"Server Error (update_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def delete_item(page_id_str):
    global active_notion_session
    if not active_notion_session:
        return jsonify({"error": "Notion session not active"}), 500

    app.logger.info(f"Archiving page: {page_id_str}")
    try:
        page_obj = active_notion_session.get_page(page_id_str)
        if not page_obj: 
            return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404
        
        page_obj.archive() 
        app.logger.info(f"Successfully archived page: {page_id_str}")
        return jsonify({"message": f"Item {page_id_str} archived successfully."}), 200 
    except Exception as e:
        app.logger.error(f"Server Error (delete_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def _close_notion_session():
    """Helper function to close the Notion session on exit."""
    global active_notion_session
    if active_notion_session and hasattr(active_notion_session, 'close') and callable(active_notion_session.close):
        try:
            print(" * Closing Notion session...")
            active_notion_session.close()
            print(" * Notion session closed.")
        except Exception as e:
            print(f"Error closing Notion session: {e}", file=sys.stderr)

def run_app_logic():
    """Main application logic: DB selection, schema fetching, and starting Flask."""
    global active_notion_session, db_obj, SCHEMA_DICT, PROPERTIES_SCHEMA, DB_ID, DB_NAME_SLUG, app

    NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
    if not NOTION_API_TOKEN:
        print("Error: Missing Notion API key. Set NOTION_API_TOKEN in your environment.", file=sys.stderr)
        exit(1)

    try:
        # Set the environment variable for the session
        os.environ["NOTION_TOKEN"] = NOTION_API_TOKEN
        active_notion_session = Session()
        print(" * Ultimate Notion session initialized and active for the application lifetime.")
        atexit.register(_close_notion_session)
    except Exception as e:
        print(f"Fatal Error: Could not initialize Notion session. {e}", file=sys.stderr)
        exit(1)

    available_databases = fetch_databases_un(active_notion_session)
    if not available_databases:
        print("Could not retrieve database list. Exiting.", file=sys.stderr)
        return 

    selected_db_user_info = display_databases_and_get_choice(available_databases)
    if not selected_db_user_info:
        print("No database selected. Exiting.", file=sys.stderr)
        return

    retrieved_properties = get_database_properties_un(active_notion_session, selected_db_user_info["id"])

    if retrieved_properties and not db_obj.is_empty: 
        DB_ID = str(db_obj.id)
        
        db_actual_name = "Untitled Database" 
        if db_obj.title:
            if hasattr(db_obj.title, 'plain_text'):
                db_actual_name = db_obj.title.plain_text
            elif hasattr(db_obj.title, 'text'):
                db_actual_name = db_obj.title.text
            else:
                db_actual_name = str(db_obj.title)
        elif selected_db_user_info.get("name") != "Untitled Database": 
             db_actual_name = selected_db_user_info.get("name")

        SCHEMA_DICT = {
            "database_id": DB_ID,
            "database_name": db_actual_name,
            "properties": retrieved_properties 
        }
        PROPERTIES_SCHEMA = SCHEMA_DICT['properties'] 
        
        DB_NAME_SLUG = re.sub(r'[^\w]+', '_', db_actual_name.lower()).strip('_')
        if not DB_NAME_SLUG: 
            DB_NAME_SLUG = DB_ID.replace('-', '_')

        print(f" * Database selected: '{SCHEMA_DICT['database_name']}' (ID: {DB_ID}, Slug: {DB_NAME_SLUG})")
        print(f" * Schema has {len(PROPERTIES_SCHEMA)} properties.")

        api_base = f"/api/{DB_NAME_SLUG}"

        app.add_url_rule(api_base, endpoint='list_items_endpoint', view_func=list_items, methods=['GET'])
        app.add_url_rule(f"{api_base}/<page_id_str>", endpoint='get_item_endpoint', view_func=get_item, methods=['GET'])
        app.add_url_rule(api_base, endpoint='create_item_endpoint', view_func=create_item, methods=['POST'])
        app.add_url_rule(f"{api_base}/<page_id_str>", endpoint='update_item_endpoint', view_func=update_item, methods=['PUT', 'PATCH'])
        app.add_url_rule(f"{api_base}/<page_id_str>", endpoint='delete_item_endpoint', view_func=delete_item, methods=['DELETE'])

        @app.route(f"{api_base}/schema", methods=['GET'])
        def get_schema():
            if SCHEMA_DICT:
                return jsonify(SCHEMA_DICT)
            return jsonify({"error": "Schema not available"}), 500

        print(f" * API endpoints registered for base path: {api_base}")
        print(f" * Schema available at: {api_base}/schema")

        parser = argparse.ArgumentParser(description="Flask API Server for Notion DB (ultimate-notion Session)")
        parser.add_argument("-p", "--port", type=int, default=5002, help="Port for Flask server.")
        cli_args, _ = parser.parse_known_args()
        port = cli_args.port

        print(f" --- Starting Flask server for '{SCHEMA_DICT['database_name']}' on http://127.0.0.1:{port}{api_base} --- ")
        app.run(host='0.0.0.0', debug=True, port=port, use_reloader=False)
    else:
        print(f"Error: Failed to retrieve schema for database '{selected_db_user_info.get('name', 'N/A') if selected_db_user_info else 'Unknown'}'. Exiting.", file=sys.stderr)
        return

# --- Main Execution ---
if __name__ == '__main__':
    run_app_logic()

