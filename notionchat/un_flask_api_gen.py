# flask_api_generator.py
# Runs Flask API for one selected Notion DB. Fetches schema using ultimate-notion with Session context.
import os
import re
import sys
import json
import argparse
from flask import Flask, request, jsonify
from datetime import date, datetime

# --- Ultimate Notion Client Initialization ---
try:
    from ultimate_notion import Session # Changed from NotionClient
    from ultimate_notion.obj.page import Page
    from ultimate_notion.obj.database import Database
    from ultimate_notion.obj.user import User
    # Import PropertyValue types for more specific handling in simplify_notion_page_un
    from ultimate_notion.obj.properties import (
        PropertyValue, TitlePropertyValue, RichTextPropertyValue, NumberPropertyValue,
        SelectPropertyValue, MultiSelectPropertyValue, StatusPropertyValue, DatePropertyValue,
        PeoplePropertyValue, FilesPropertyValue, CheckboxPropertyValue, URLPropertyValue,
        EmailPropertyValue, PhoneNumberPropertyValue, FormulaPropertyValue, RelationPropertyValue,
        RollupPropertyValue, CreatedTimePropertyValue, CreatedByPropertyValue,
        LastEditedTimePropertyValue, LastEditedByPropertyValue
    )
    from ultimate_notion.obj.property_values import DateRange, RichText # For type hints and access
    from ultimate_notion.obj.options import SelectOption # For type hints
    from ultimate_notion.query import Filter, CompoundFilter, PropertyFilter # Sorts not used yet but good to have
    from ultimate_notion.obj.errors import NotionAPIError, ObjectNotFoundError
    # from ultimate_notion.schema import PropertySchema # Not directly used for dynamic schema yet
except ImportError:
    print("Error: ultimate-notion library not found. Please install it: pip install ultimate-notion", file=sys.stderr)
    exit(1)


# --- Global Variables ---
# These will be initialized after the Notion session starts and DB is selected.
db_obj: Database | None = None
SCHEMA_DICT: dict | None = None # Renamed from SCHEMA
PROPERTIES_SCHEMA: dict | None = None # This is db_obj.schema_dict() essentially
DB_ID: str | None = None
DB_NAME_SLUG: str | None = None

# This will hold the active ultimate-notion session.
# Made global to be easily accessible by Flask route handlers within the `run_app` structure.
active_notion_session: Session | None = None

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# --- Functions ---

def fetch_databases_un(notion_ses: Session): # Accepts session
    """Fetches accessible databases from Notion using ultimate-notion."""
    print(" * Fetching accessible databases from Notion (using ultimate-notion Session)...")
    try:
        all_db_objects = list(notion_ses.search_db()) # Use session object
        all_databases = []
        for db_item in all_db_objects:
            if db_item and db_item.title:
                db_name = str(db_item.title.value.plain_text) if db_item.title.value else "Untitled Database"
                db_id = str(db_item.id)
                all_databases.append({"name": db_name, "id": db_id})
        
        print(f" * Found {len(all_databases)} databases.")
        return all_databases
    except NotionAPIError as error:
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
        except EOFError:
            print("\nInput stream closed unexpectedly.")
            return None

def get_database_properties_un(notion_ses: Session, database_id: str):
    """Retrieves the properties schema for a given database ID using ultimate-notion."""
    global db_obj # Allow modification of the global db_obj
    print(f" * Retrieving schema for database ID: {database_id} (using ultimate-notion Session)...")
    try:
        db_obj = notion_ses.get_db(database_id) # Use session, sets global db_obj
        if not db_obj:
            print(f"Error: Could not retrieve database with ID {database_id}", file=sys.stderr)
            return None
        
        properties_schema = db_obj.schema_dict()
        print(" * Schema retrieved successfully.")
        return properties_schema
    except ObjectNotFoundError:
        print(f"Error: Database with ID {database_id} not found.", file=sys.stderr)
        return None
    except NotionAPIError as error:
        print(f"Error retrieving schema for DB ID {database_id}: {error}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Error retrieving properties for DB ID {database_id}: {e}", file=sys.stderr)
        return None

# --- Notion API Interaction Helpers (with Ultimate Notion) ---

def build_notion_filter_un(query_params: dict) -> Filter | None:
    """
    Translates Flask query parameters into an Ultimate Notion Filter object.
    Uses global PROPERTIES_SCHEMA.
    """
    if not query_params or not PROPERTIES_SCHEMA: # Check if PROPERTIES_SCHEMA is populated
        return None

    filter_conditions = []
    # Create a lower-case mapping of actual schema property names for case-insensitive lookup
    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for param_name_lower, param_value in query_params.items():
        param_name_lower = param_name_lower.lower()
        matched_prop_name = schema_props_lower.get(param_name_lower)

        if not matched_prop_name:
            app.logger.warning(f"Query parameter '{param_name_lower}' not found in schema, skipping filter.")
            continue

        prop_schema_dict = PROPERTIES_SCHEMA[matched_prop_name] # Get schema details for this property
        prop_type = prop_schema_dict['type'] # Notion API type string (e.g. 'number', 'select')

        condition: PropertyFilter | None = None
        try:
            prop_filter_obj = Filter.prop(matched_prop_name) 

            if prop_type in ['rich_text', 'title', 'email', 'phone_number', 'url']:
                condition = prop_filter_obj.equals(param_value)
            elif prop_type == 'number':
                condition = prop_filter_obj.equals(float(param_value))
            elif prop_type == 'select':
                condition = prop_filter_obj.equals(param_value) # Filter by option name
            elif prop_type == 'multi_select':
                condition = prop_filter_obj.contains(param_value) # Filter by option name
            elif prop_type == 'checkbox':
                condition = prop_filter_obj.equals(param_value.lower() == 'true')
            elif prop_type == 'date':
                condition = prop_filter_obj.equals(param_value) # Assumes YYYY-MM-DD
            elif prop_type == 'status':
                condition = prop_filter_obj.equals(param_value) # Filter by status name
            elif prop_type == 'people': 
                condition = prop_filter_obj.contains(param_value) # Assumes value is user ID
            elif prop_type == 'relation': 
                condition = prop_filter_obj.contains(param_value) # Assumes value is page ID
            
            if condition:
                filter_conditions.append(condition)
            else:
                app.logger.warning(f"Filtering not implemented for type '{prop_type}' (property: '{matched_prop_name}') or value was problematic.")
        except ValueError:
            app.logger.warning(f"Could not convert value '{param_value}' for property '{matched_prop_name}' (type: {prop_type}), skipping filter.")
        except Exception as e:
            app.logger.error(f"Error building filter for {matched_prop_name}: {e}, skipping.")

    if not filter_conditions: return None
    return filter_conditions[0] if len(filter_conditions) == 1 else CompoundFilter.logic_and(*filter_conditions)


def build_notion_properties_payload_un(data: dict) -> dict:
    """
    Translates incoming JSON data into a dictionary suitable for ultimate-notion's
    create_page kwargs or page.set_prop_value. Uses global PROPERTIES_SCHEMA.
    """
    properties_payload = {}
    if not PROPERTIES_SCHEMA: return properties_payload # Guard clause

    schema_props_lower = {name.lower(): name for name in PROPERTIES_SCHEMA.keys()}

    for input_key, value in data.items():
        input_key_lower = input_key.lower()
        matched_prop_name = schema_props_lower.get(input_key_lower)

        if not matched_prop_name:
            app.logger.warning(f"Property '{input_key}' not found in schema, skipping.")
            continue
        
        prop_schema_dict = PROPERTIES_SCHEMA[matched_prop_name]
        prop_type = prop_schema_dict['type']
        
        try:
            if value is None: # Handle null values to clear fields
                if prop_type not in ['checkbox', 'status']: # These might not be clearable with None directly
                    properties_payload[matched_prop_name] = None
                continue

            # Process non-null values based on expected types for ultimate-notion
            if prop_type in ['title', 'rich_text', 'email', 'phone_number', 'url', 'select', 'status']:
                properties_payload[matched_prop_name] = str(value)
            elif prop_type == 'number':
                properties_payload[matched_prop_name] = float(value) if value != "" else None
            elif prop_type == 'multi_select': # Expects a list of names
                properties_payload[matched_prop_name] = [str(item) for item in value] if isinstance(value, list) else [str(value)]
            elif prop_type == 'date': # Expects ISO string, date, or datetime object
                properties_payload[matched_prop_name] = str(value) 
            elif prop_type == 'checkbox':
                properties_payload[matched_prop_name] = bool(value)
            elif prop_type in ['people', 'relation']: # Expects list of IDs
                properties_payload[matched_prop_name] = [str(item_id) for item_id in value] if isinstance(value, list) else [str(value)]
            else:
                app.logger.warning(f"Payload generation for type '{prop_type}' (prop: '{matched_prop_name}') using direct value.")
                properties_payload[matched_prop_name] = value # Pass as is
        
        except (ValueError, TypeError) as e:
            app.logger.warning(f"Could not format value '{value}' for property '{matched_prop_name}' (type: {prop_type}): {e}, skipping.")
        except Exception as e:
            app.logger.error(f"Error building payload for {matched_prop_name}: {e}, skipping.")
            
    return properties_payload

def simplify_notion_page_un(page: Page) -> dict:
    """
    Simplifies an ultimate-notion Page object into a flatter dictionary for JSON response.
    Uses global PROPERTIES_SCHEMA and db_obj.
    Relies on page.get_prop_value(prop_name).value for typed data.
    """
    simplified = {"page_id": str(page.id), "page_url": page.url}
    if page.archived: simplified["archived"] = True
    
    if not PROPERTIES_SCHEMA or not db_obj: # Should be populated
        app.logger.error("PROPERTIES_SCHEMA or db_obj not available for page simplification.")
        return simplified

    for prop_name, prop_schema_details in PROPERTIES_SCHEMA.items():
        prop_api_type = prop_schema_details['type'] # Notion's API type string
        ui_value = None # Value to be put in the simplified JSON

        try:
            # Get the PropertyValue object (e.g., TitlePropertyValue, NumberPropertyValue)
            # For title, page.title is a direct TitlePropertyValue
            if prop_name == db_obj.title_prop_name:
                prop_value_obj = page.title
            else:
                prop_value_obj = page.get_prop_value(prop_name)

            if prop_value_obj is None or not hasattr(prop_value_obj, 'value') or prop_value_obj.value is None:
                ui_value = None # Property has no value or value is None
            else:
                # core_value is the Pythonic representation (e.g., RichText obj, float, SelectOption, list of Users)
                core_value = prop_value_obj.value 

                # --- Convert core_value to JSON serializable ui_value based on prop_api_type ---
                if prop_api_type == 'title' or prop_api_type == 'rich_text': # core_value is RichText
                    ui_value = core_value.plain_text
                elif prop_api_type == 'number': # core_value is float or int
                    ui_value = core_value
                elif prop_api_type == 'select' or prop_api_type == 'status': # core_value is SelectOption/StatusOption
                    ui_value = core_value.name
                elif prop_api_type == 'multi_select': # core_value is list[SelectOption]
                    ui_value = [opt.name for opt in core_value]
                elif prop_api_type == 'date': # core_value is DateRange
                    ui_value = {"start": core_value.start.isoformat() if core_value.start else None,
                                "end": core_value.end.isoformat() if core_value.end else None}
                elif prop_api_type == 'people': # core_value is list[User]
                    ui_value = [{"id": str(user.id), "name": user.name, "type": "user"} for user in core_value]
                elif prop_api_type == 'relation': # core_value is list[Page] (stubs)
                    ui_value = [{"id": str(p.id), 
                                 "title": p.title.value.plain_text if p.title and p.title.value else "Untitled Relation"} 
                                for p in core_value]
                elif prop_api_type == 'files': # core_value is list[File] (File objects from ultimate_notion)
                    ui_value = [{"name": f.name, "url": f.url if hasattr(f, 'url') else None} for f in core_value]
                elif prop_api_type == 'checkbox': # core_value is bool
                    ui_value = core_value
                elif prop_api_type in ['url', 'email', 'phone_number']: # core_value is str
                    ui_value = core_value
                elif prop_api_type == 'formula': # core_value is FormulaResult
                    # FormulaResult has .type and .string, .number, .boolean, .date
                    if core_value.type == 'string': ui_value = core_value.string
                    elif core_value.type == 'number': ui_value = core_value.number
                    elif core_value.type == 'boolean': ui_value = core_value.boolean
                    elif core_value.type == 'date': 
                        ui_value = core_value.date.start.isoformat() if core_value.date and core_value.date.start else None
                elif prop_api_type == 'rollup': # core_value is RollupValue
                    # RollupValue has .type and specific result attributes (.number, .date, .array)
                    if core_value.type == 'number': ui_value = core_value.number
                    elif core_value.type == 'date': 
                        ui_value = core_value.date.start.isoformat() if core_value.date and core_value.date.start else None
                    elif core_value.type == 'array':
                        # Rollup array contains other PropertyValue items. This can be complex.
                        # For simplicity, try to extract plain text or simple values from array items.
                        arr_values = []
                        for item_pv in core_value.array: # item_pv is a PropertyValue
                            if hasattr(item_pv, 'value') and item_pv.value is not None:
                                if isinstance(item_pv.value, RichText): arr_values.append(item_pv.value.plain_text)
                                elif isinstance(item_pv.value, SelectOption): arr_values.append(item_pv.value.name)
                                elif isinstance(item_pv.value, (str, int, float, bool)): arr_values.append(item_pv.value)
                                elif isinstance(item_pv.value, DateRange): arr_values.append(item_pv.value.start.isoformat() if item_pv.value.start else None)
                                else: arr_values.append(str(item_pv.value)) # Fallback
                            else: arr_values.append(None)
                        ui_value = arr_values
                    else: ui_value = f"Unsupported rollup type: {core_value.type}"
                elif prop_api_type in ['created_time', 'last_edited_time']: # core_value is datetime
                    ui_value = core_value.isoformat()
                elif prop_api_type in ['created_by', 'last_edited_by']: # core_value is User
                    ui_value = {"id": str(core_value.id), "name": core_value.name, "type": "user"}
                else:
                    app.logger.warning(f"Simplification for API type '{prop_api_type}' (prop: {prop_name}) not fully defined. Using str().")
                    ui_value = str(core_value)
            
            simplified[prop_name] = ui_value

        except Exception as e:
            app.logger.error(f"Error simplifying property '{prop_name}' (API type: {prop_api_type}) for page {page.id}: {e}", exc_info=True)
            simplified[prop_name] = f"Error processing property '{prop_name}'"
            
    return simplified

# --- Flask App Route Definitions ---
# These are defined globally but will use global variables (DB_NAME_SLUG, db_obj, active_notion_session)
# set within the run_app() context. This is a common pattern for single-file Flask apps
# where routes are dynamic based on startup configuration.

@app.route("/api/placeholder_db_slug", methods=['GET']) # Placeholder, will be replaced
def list_items():
    global db_obj, DB_ID # Access globals
    if not db_obj or not DB_ID:
        return jsonify({"error": "Database object not initialized or DB_ID missing"}), 500

    query_params = request.args.to_dict()
    notion_filter_obj = build_notion_filter_un(query_params)
    
    app.logger.info(f"Executing Query on DB: {DB_ID}")
    app.logger.info(f"Filters received: {query_params}")
    if notion_filter_obj: app.logger.debug(f"Ultimate Notion filter: {notion_filter_obj}")
    
    try:
        query_builder = db_obj.query(filter=notion_filter_obj)
        page_size_str = query_params.get('page_size')
        start_cursor_str = query_params.get('start_cursor')
        if page_size_str: query_builder = query_builder.page_size(int(page_size_str))
        if start_cursor_str: query_builder = query_builder.start_cursor(start_cursor_str)
        
        all_page_objects = list(query_builder) # Fetches pages
        simplified_results = [simplify_notion_page_un(page_obj) for page_obj in all_page_objects]
        return jsonify(simplified_results)
    except NotionAPIError as error:
        app.logger.error(f"Notion API Error (list_items): {error}")
        return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), error.status_code or 500
    except Exception as e:
        app.logger.error(f"Server Error (list_items): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

@app.route("/api/placeholder_db_slug/<page_id_str>", methods=['GET']) # Placeholder
def get_item(page_id_str):
    global active_notion_session # Access global session
    if not active_notion_session:
        return jsonify({"error": "Notion session not active"}), 500
        
    app.logger.info(f"Retrieving page: {page_id_str}")
    try:
        page_obj = active_notion_session.get_page(page_id_str)
        simplified_page = simplify_notion_page_un(page_obj)
        return jsonify(simplified_page)
    except ObjectNotFoundError:
        app.logger.info(f"Page not found: {page_id_str}")
        return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404
    except NotionAPIError as error:
        app.logger.error(f"Notion API Error (get_item {page_id_str}): {error}")
        return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), error.status_code or 500
    except Exception as e:
        app.logger.error(f"Server Error (get_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

@app.route("/api/placeholder_db_slug", methods=['POST']) # Placeholder
def create_item():
    global db_obj, active_notion_session # Access globals
    if not db_obj or not active_notion_session: 
        return jsonify({"error": "Database or session not initialized"}), 500
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400
    
    data = request.get_json()
    app.logger.info(f"Received data for creation: {data}")
    properties_for_un = build_notion_properties_payload_un(data)
    if not properties_for_un and data: # If data was provided but resulted in no valid props
        return jsonify({"error": "Bad Request", "message": "No valid properties found in payload."}), 400
    if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}),400

    app.logger.debug(f"Payload for create: {json.dumps(properties_for_un, indent=2, default=str)}")

    try:
        title_prop_name = db_obj.title_prop_name # Name of the title property (e.g., "Name")
        title_value = properties_for_un.pop(title_prop_name, None) # Extract title value if present

        # Create page using db_obj.create_page, passing title and other properties as kwargs
        # Note: ultimate-notion's create_page expects the title property's value under its actual name.
        # So, if title_prop_name was 'Task Name', it expects `Task Name="My new task"`
        create_kwargs = {}
        if title_value is not None:
            create_kwargs[title_prop_name] = title_value 
        create_kwargs.update(properties_for_un) # Add remaining properties

        if not create_kwargs: # Ensure there's something to create the page with
             app.logger.warning("Attempting to create a page with an empty properties payload.")
             # Depending on Notion rules, this might fail or create an untitled page.
             # Consider if a title is mandatory. For now, proceed.

        new_page_obj = db_obj.create_page(**create_kwargs)
        simplified_page = simplify_notion_page_un(new_page_obj)
        app.logger.info(f"Successfully created page: {new_page_obj.id}")
        return jsonify(simplified_page), 201
    except NotionAPIError as error:
        app.logger.error(f"Notion API Error (create_item): {error}")
        return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), error.status_code or 500
    except Exception as e:
        app.logger.error(f"Server Error (create_item): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

@app.route("/api/placeholder_db_slug/<page_id_str>", methods=['PUT', 'PATCH']) # Placeholder
def update_item(page_id_str):
    global active_notion_session, db_obj # Access globals
    if not active_notion_session or not db_obj:
        return jsonify({"error": "Notion session or DB object not active"}), 500
    if not request.is_json: return jsonify({"error": "Bad Request", "message": "Request must be JSON"}), 400
    
    data = request.get_json()
    app.logger.info(f"Data for update ({page_id_str}): {data}")
    properties_to_update = build_notion_properties_payload_un(data)
    if not properties_to_update and data:
         return jsonify({"error": "Bad Request", "message": "No valid properties found in payload for update."}), 400
    if not data: return jsonify({"error": "Bad Request", "message": "Request body is empty."}),400

    app.logger.debug(f"Payload for update ({page_id_str}): {json.dumps(properties_to_update, indent=2, default=str)}")

    try:
        page_obj = active_notion_session.get_page(page_id_str)
        
        title_prop_name = db_obj.title_prop_name
        for prop_name, value in properties_to_update.items():
            if prop_name == title_prop_name:
                page_obj.title = value # Sets the RichText value for the title
            else:
                page_obj.set_prop_value(prop_name, value)
        
        page_obj.update() # Persist changes
        
        simplified_page = simplify_notion_page_un(page_obj) # page_obj is updated in-place
        app.logger.info(f"Successfully updated page: {page_id_str}")
        return jsonify(simplified_page)
    except ObjectNotFoundError:
        app.logger.info(f"Page not found for update: {page_id_str}")
        return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404
    except NotionAPIError as error:
        app.logger.error(f"Notion API Error (update_item {page_id_str}): {error}")
        return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), error.status_code or 500
    except Exception as e:
        app.logger.error(f"Server Error (update_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

@app.route("/api/placeholder_db_slug/<page_id_str>", methods=['DELETE']) # Placeholder
def delete_item(page_id_str):
    global active_notion_session # Access global session
    if not active_notion_session:
        return jsonify({"error": "Notion session not active"}), 500

    app.logger.info(f"Archiving page: {page_id_str}")
    try:
        page_obj = active_notion_session.get_page(page_id_str)
        page_obj.archive()
        app.logger.info(f"Successfully archived page: {page_id_str}")
        return jsonify({"message": f"Item {page_id_str} archived successfully."}), 200
    except ObjectNotFoundError:
        app.logger.info(f"Page not found for delete: {page_id_str}")
        return jsonify({"error": "Not Found", "message": f"Item with ID {page_id_str} not found."}), 404
    except NotionAPIError as error:
        app.logger.error(f"Notion API Error (delete_item {page_id_str}): {error}")
        return jsonify({"error": f"Notion API Error: {error.code}", "message": str(error)}), error.status_code or 500
    except Exception as e:
        app.logger.error(f"Server Error (delete_item {page_id_str}): {e}", exc_info=True)
        return jsonify({"error": "Internal server error", "message": str(e)}), 500

def _update_flask_routes(app_instance, base_slug):
    """
    Helper to update route rules after the DB slug is known.
    This is a bit of a workaround for dynamic route paths in a single-file app.
    A Blueprint approach would be cleaner for larger apps.
    """
    new_rules = []
    for rule in app_instance.url_map.iter_rules():
        if "placeholder_db_slug" in rule.rule:
            new_rule_string = rule.rule.replace("placeholder_db_slug", base_slug)
            new_rules.append((new_rule_string, rule.endpoint, rule.methods))
        else: # Keep non-dynamic rules if any
            new_rules.append((rule.rule, rule.endpoint, rule.methods))
    
    # Clear existing rules and add new ones
    # This is somewhat fragile and depends on Flask internals not changing drastically.
    # For Flask 2.x, app.url_map._rules and app.url_map._rules_by_endpoint might need direct manipulation
    # or re-adding endpoints. Simpler: create a new app or use Blueprints.
    # Given the constraints, we'll try a simpler re-add if direct replacement is too complex.

    # For this script, since routes are simple, we can just re-add them with new paths.
    # This requires endpoint names to be unique if we were to add them without removing.
    # Let's assume the placeholder routes are sufficient for Flask to map function names,
    # and we just need to update the URL strings.
    
    # A more robust way for this specific case: define routes within run_app *after* slug is known.
    # This means moving the @app.route decorators into run_app or a function called from there.
    # This is what I will do.

    pass # This helper will not be used; routes will be defined dynamically.


def run_app_logic():
    """Main application logic: DB selection, schema fetching, and starting Flask."""
    global active_notion_session, db_obj, SCHEMA_DICT, PROPERTIES_SCHEMA, DB_ID, DB_NAME_SLUG, app

    NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN")
    if not NOTION_API_TOKEN:
        print("Error: Missing Notion API key. Set NOTION_API_TOKEN in your environment.", file=sys.stderr)
        exit(1)

    with Session.get_or_create(token=NOTION_API_TOKEN) as notion_ses:
        active_notion_session = notion_ses # Set global session
        print(" * Ultimate Notion session started.")

        available_databases = fetch_databases_un(active_notion_session)
        if not available_databases:
            print("Could not retrieve database list. Exiting.", file=sys.stderr)
            return

        selected_db_user_info = display_databases_and_get_choice(available_databases)
        if not selected_db_user_info:
            print("No database selected. Exiting.", file=sys.stderr)
            return

        # This sets the global db_obj
        retrieved_properties = get_database_properties_un(active_notion_session, selected_db_user_info["id"])
        
        if retrieved_properties and db_obj:
            # Populate global config variables
            DB_ID = str(db_obj.id)
            # Use db_obj.title (TitlePropertyValue) for consistent name source
            db_title_rich_text = db_obj.title.value if db_obj.title else None
            db_actual_name = db_title_rich_text.plain_text if db_title_rich_text else selected_db_user_info["name"]
            
            SCHEMA_DICT = {
                "database_id": DB_ID,
                "database_name": db_actual_name,
                "properties": retrieved_properties # This is db_obj.schema_dict()
            }
            PROPERTIES_SCHEMA = SCHEMA_DICT['properties']
            DB_NAME_SLUG = re.sub(r'[^\w]+', '_', SCHEMA_DICT['database_name'].lower()).strip('_')
            if not DB_NAME_SLUG: DB_NAME_SLUG = DB_ID.replace('-', '_') # Fallback slug

            print(f" * Database selected: '{SCHEMA_DICT['database_name']}' (ID: {DB_ID}, Slug: {DB_NAME_SLUG})")
            print(f" * Schema has {len(PROPERTIES_SCHEMA)} properties.")

            # --- Dynamically Define Flask Routes ---
            # Now that DB_NAME_SLUG is known, we can define the routes with correct paths.
            api_base = f"/api/{DB_NAME_SLUG}"
            
            # Add rules using the dynamically generated api_base
            # Functions list_items, get_item etc. are already defined globally.
            # Flask allows adding URL rules imperatively.
            app.add_url_rule(api_base, view_func=list_items, methods=['GET'])
            app.add_url_rule(f"{api_base}/<page_id_str>", view_func=get_item, methods=['GET'])
            app.add_url_rule(api_base, view_func=create_item, methods=['POST'])
            app.add_url_rule(f"{api_base}/<page_id_str>", view_func=update_item, methods=['PUT', 'PATCH'])
            app.add_url_rule(f"{api_base}/<page_id_str>", view_func=delete_item, methods=['DELETE'])
            
            print(f" * API endpoints registered for base path: {api_base}")

            # --- Argument Parser for Port ---
            parser = argparse.ArgumentParser(description="Flask API Server for Notion DB (ultimate-notion Session)")
            parser.add_argument("-p", "--port", type=int, default=5002, help="Port for Flask server.")
            cli_args, _ = parser.parse_known_args()
            port = cli_args.port

            print(f" --- Starting Flask server for '{SCHEMA_DICT['database_name']}' on port {port} --- ")
            app.run(debug=True, port=port, use_reloader=False) # use_reloader=False is important!
        else:
            print(f"Error: Failed to retrieve schema for database '{selected_db_user_info['name']}'. Exiting.", file=sys.stderr)
            return

# --- Main Execution ---
if __name__ == '__main__':
    # Conceptual note on dynamic uno.Schema:
    # If we were to generate a dynamic schema class (e.g., `MyDynamicSchema(uno.Schema)`),
    # we could potentially use it to wrap Page objects: `typed_page = MyDynamicSchema.wrap_page(page_obj)`.
    # This might allow attribute access like `typed_page.props.MyPropertyName`.
    # However, generating `MyDynamicSchema` correctly (mapping Notion types to uno.PropType,
    # handling all uno.Property options) at runtime for any arbitrary database is complex.
    # For now, `page.get_prop_value()` and `page.set_prop_value()` provide robust dynamic access.
    run_app_logic()

