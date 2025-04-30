#!/usr/bin/python3
# -*- coding:utf-8 -*-

import sys
import logging
import array
import subprocess

# D-Bus / GLib related imports
import pydbus
from gi.repository import GLib, Gio # Gio might still be useful elsewhere, keep it for now

# --- Configuration ---
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
CMD_CHAR_UUID = "133934e1-01f5-4054-a88f-0136e064c49e" # Write
STATUS_CHAR_UUID = "133934e2-01f5-4054-a88f-0136e064c49e" # Read, Notify
SSID_CHAR_UUID = "133934e3-01f5-4054-a88f-0136e064c49e" # Read, Notify

# D-Bus Service Names and Paths
BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
ADAPTER_IFACE = 'org.bluez.Adapter1'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE =    'org.bluez.GattCharacteristic1'
DBUS_OM_IFACE =      'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE =    'org.freedesktop.DBus.Properties'

# Define a unique service name for our application on the D-Bus
APP_BUS_NAME = 'com.btpifi.server'

# Define object paths
APP_OBJECT_ROOT = '/com/btpifi' # Root path MUST implement ObjectManager
SERVICE_PATH = f'{APP_OBJECT_ROOT}/service0'
CMD_CHAR_PATH = f'{APP_OBJECT_ROOT}/service0/char0'
STATUS_CHAR_PATH = f'{APP_OBJECT_ROOT}/service0/char1'
SSID_CHAR_PATH = f'{APP_OBJECT_ROOT}/service0/char2'
AD_PATH_BASE = f'{APP_OBJECT_ROOT}/advertisement' # Base path for advertisements
ADVERTISEMENT_PATH = f'{AD_PATH_BASE}0' # Full path for the single advertisement


# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global State ---
current_status = "Idle".encode('utf-8')
scanned_ssids_json = "[]".encode('utf-8')
mainloop = None
bus = None
# Global references to characteristic instances for notification sending
cmd_char = None
status_char = None
ssid_char = None
# Keep references to prevent garbage collection
_app_objects = {} # Store all GATT objects managed by ObjectManager
advertisement = None # Keep reference to advertisement object
app_manager = None # Keep reference to object manager


# --- Base Property Class ---
class BluezPropertyInterface(object):
    """ Base class for implementing BlueZ D-Bus Property Interfaces """
    INTERFACE_NAME = DBUS_PROP_IFACE

    def Get(self, interface_name, prop_name):
        if not hasattr(self, 'interface_name'): raise NotImplementedError("Subclass must define self.interface_name")
        if interface_name == self.interface_name:
            props = self.GetAll(interface_name)
            if prop_name in props: return props[prop_name]
            else: logger.error(f"Property {prop_name} not found in {interface_name}"); raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Property Not Found")
        else: logger.error(f"Interface mismatch in Get: req={interface_name}, exp={self.interface_name}"); raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Interface Not Found")

    def Set(self, interface_name, prop_name, value):
        logger.warning(f"Set called on {prop_name} - not implemented (read-only)")
        raise pydbus.dbus.DBusException("o.f.DBus.Error.PropertyReadOnly", "Property ReadOnly")

    def GetAll(self, interface_name): raise NotImplementedError("Subclass must implement GetAll")

# --- D-Bus GATT Service Implementation ---
class WifiConfigService(BluezPropertyInterface):
    """ org.bluez.GattService1 implementation """
    __dbus_xml__ = f"""<node>
        <interface name='{GATT_SERVICE_IFACE}'>
            <property name='UUID' type='s' access='read'/>
            <property name='Primary' type='b' access='read'/>
            <property name='Characteristics' type='ao' access='read'/>
        </interface>
        <interface name='{DBUS_PROP_IFACE}'>
            <method name='Get'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='out'/></method>
            <method name='Set'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='in'/></method>
            <method name='GetAll'><arg type='s' direction='in'/><arg type='a{{sv}}' direction='out'/></method>
        </interface>
    </node>"""
    INTERFACE_NAME = GATT_SERVICE_IFACE

    def __init__(self, path, uuid, characteristics):
        self.path = path; self._uuid = uuid; self._primary = True
        self._characteristics_instances = characteristics
        self._characteristics_paths = [c.path for c in characteristics]
        logger.info(f"Initializing Service: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_SERVICE_IFACE # Set interface_name for base class

    @property
    def UUID(self): return self._uuid
    @property
    def Primary(self): return self._primary
    @property
    def Characteristics(self): return self._characteristics_paths

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self._uuid,
                'Primary': self._primary,
                'Characteristics': self._characteristics_paths
            }
        }

    def GetAll(self, interface_name):
        if interface_name == self.INTERFACE_NAME:
            # Note: pydbus expects actual values, not GLib.Variant here for GetAll
            return {
                'UUID': self._uuid,
                'Primary': self._primary,
                'Characteristics': self._characteristics_paths
            }
        else:
            logger.error(f"GetAll called for incorrect interface: {interface_name} on {self.path}")
            raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Interface Not Found")


# --- D-Bus GATT Characteristic Implementations ---
CHARACTERISTIC_DBUS_XML = f"""<node>
    <interface name='{GATT_CHRC_IFACE}'>
        <method name='ReadValue'><arg type='a{{sv}}' name='options' direction='in'/><arg type='ay' name='value' direction='out'/></method>
        <method name='WriteValue'><arg type='ay' name='value' direction='in'/><arg type='a{{sv}}' name='options' direction='in'/></method>
        <method name='StartNotify'/>
        <method name='StopNotify'/>
        <property name='UUID' type='s' access='read'/>
        <property name='Service' type='o' access='read'/>
        <property name='Value' type='ay' access='read'/>
        <property name='Notifying' type='b' access='read'/>
        <property name='Flags' type='as' access='read'/>
    </interface>
    <interface name='{DBUS_PROP_IFACE}'>
        <method name='Get'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='out'/></method>
        <method name='Set'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='in'/></method>
        <method name='GetAll'><arg type='s' direction='in'/><arg type='a{{sv}}' direction='out'/></method>
        <signal name='PropertiesChanged'>
            <arg type='s' name='interface_name'/>
            <arg type='a{{sv}}' name='changed_properties'/>
            <arg type='as' name='invalidated_properties'/>
        </signal>
    </interface>
</node>"""

class WifiCommandCharacteristic(BluezPropertyInterface):
    """ org.bluez.GattCharacteristic1 implementation for Write commands. """
    __dbus_xml__ = CHARACTERISTIC_DBUS_XML
    INTERFACE_NAME = GATT_CHRC_IFACE # Set interface_name for base class

    def __init__(self, path, uuid, service_path):
        self.path = path; self._uuid = uuid; self._service_path = service_path
        self._flags = ['write', 'write-without-response']
        # Value property is technically read-only here, but return empty bytes
        self._value = b''
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_CHRC_IFACE # Explicitly set again for clarity

    def ReadValue(self, options): raise pydbus.dbus.DBusException("org.bluez.Error.NotPermitted", "Read not permitted")
    def WriteValue(self, value, options):
        # Convert GLib.Variant bytes if necessary, then decode
        try:
            byte_list = [b for b in value] # Extract bytes if it's a variant or list
            command = bytes(byte_list).decode('utf-8').strip()
            logger.info(f"WriteValue called: {command}")
            # Use idle_add to ensure command handling happens in the main GLib thread
            GLib.idle_add(self.handle_command, command, priority=GLib.PRIORITY_DEFAULT_IDLE)
        except Exception as e:
            logger.error(f"Error decoding WriteValue: {e}, Raw value: {value}", exc_info=True)


    def handle_command(self, command):
        # (Command handling logic - more robust)
        logger.info(f"Handling command: {command}")
        global current_status, scanned_ssids_json, status_char, ssid_char
        new_status = None

        try:
            if command.upper() == "SCAN":
                new_status = b"Scanning..."
                logger.info("Simulating Scan...")
                # Simulate finding networks after a delay
                GLib.timeout_add_seconds(2, self.update_scan_result, b'["MyNet", "AnotherSSID", "HomeWifi"]')
            elif command.upper().startswith("CONNECT"):
                # Placeholder: Extract SSID/password if needed
                new_status = b"Connecting..."
                logger.info("Simulating Connect...")
                 # Simulate connection result after a delay
                GLib.timeout_add_seconds(3, self.update_connection_result, b"Connected") # Or b"Failed: Auth Error" etc.
            else:
                new_status = f"Error: Unknown command '{command}'".encode('utf-8')
                logger.warning(f"Unknown command received: {command}")

            if new_status is not None:
                self.update_status(new_status)

        except Exception as e:
            logger.error(f"Error handling command '{command}': {e}", exc_info=True)
            self.update_status(f"Error processing: {e}".encode('utf-8'))

        return False # Remove idle source

    def update_status(self, new_status_bytes):
        """ Safely updates the global status and notifies if needed. """
        global current_status, status_char
        if new_status_bytes != current_status:
            logger.info(f"Status -> {new_status_bytes.decode(errors='ignore')}")
            current_status = new_status_bytes
            if status_char:
                # Ensure the characteristic's internal value is updated *before* sending notification
                if status_char.update_value(current_status):
                    # Schedule notification send in main loop
                     GLib.idle_add(status_char.send_notification)


    def update_scan_result(self, result_ssids_bytes):
        """Callback to update status and SSIDs after scan"""
        global scanned_ssids_json, ssid_char
        logger.info(f"Updating scan results: {result_ssids_bytes.decode(errors='ignore')}")

        self.update_status(b"Scan Complete") # Update status first

        if result_ssids_bytes != scanned_ssids_json:
            scanned_ssids_json = result_ssids_bytes
            if ssid_char:
                if ssid_char.update_value(scanned_ssids_json):
                    GLib.idle_add(ssid_char.send_notification)

        return False # Remove timeout source

    def update_connection_result(self, result_status_bytes):
        """Callback to update status after simulated connection"""
        logger.info(f"Updating connection status to: {result_status_bytes.decode(errors='ignore')}")
        self.update_status(result_status_bytes) # Update status
        return False # Remove timeout source

    def StartNotify(self): raise pydbus.dbus.DBusException("org.bluez.Error.NotSupported", "Notify not supported")
    def StopNotify(self): pass # Do nothing, notify not supported

    @property
    def UUID(self): return self._uuid
    @property
    def Service(self): return self._service_path
    @property
    def Value(self): return array.array('y', self._value).tolist() # Return current (empty) value
    @property
    def Notifying(self): return False # Never notifying
    @property
    def Flags(self): return self._flags

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return { GATT_CHRC_IFACE: {'UUID': self._uuid, 'Service': self._service_path, 'Value': self.Value, 'Notifying': self.Notifying, 'Flags': self._flags }}

    def GetAll(self, interface_name):
        if interface_name == self.INTERFACE_NAME:
             props = self.get_properties()[GATT_CHRC_IFACE]
             # pydbus needs actual values, not variants here
             return {
                  'UUID': props['UUID'],
                  'Service': props['Service'],
                  'Value': props['Value'], # Use the property getter
                  'Notifying': props['Notifying'],
                  'Flags': props['Flags']
                  }
        else:
            logger.error(f"GetAll called for incorrect interface: {interface_name} on {self.path}")
            raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Interface Not Found")


class WifiStatusCharacteristic(BluezPropertyInterface):
    """ org.bluez.GattCharacteristic1 implementation for Read/Notify status. """
    __dbus_xml__ = CHARACTERISTIC_DBUS_XML
    INTERFACE_NAME = GATT_CHRC_IFACE # Set interface_name for base class

    PropertiesChanged = pydbus.generic.signal() # Define the signal

    def __init__(self, path, uuid, service_path):
        self.path = path; self._uuid = uuid; self._service_path = service_path
        self._flags = ['read', 'notify']; self._notifying = False
        # Initialize with the global state, ensuring it's bytes
        self._value = current_status if isinstance(current_status, bytes) else str(current_status).encode('utf-8')
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_CHRC_IFACE # Explicitly set again for clarity

    def ReadValue(self, options):
        logger.info(f"ReadValue Status: {self._value.decode(errors='ignore')}")
        return array.array('y', self._value).tolist()

    def WriteValue(self, v, o): raise pydbus.dbus.DBusException("org.bluez.Error.WriteNotPermitted", "Write not permitted")

    def StartNotify(self):
        if self._notifying:
             logger.warning(f"StartNotify called but already notifying on {self.path}")
             return
        logger.info(f"Status notifications enabled for {self.path}")
        self._notifying = True
        # Also need to signal the change in the 'Notifying' property
        self.PropertiesChanged(self.INTERFACE_NAME, {'Notifying': GLib.Variant('b', self._notifying)}, [])


    def StopNotify(self):
        if not self._notifying:
             logger.warning(f"StopNotify called but not notifying on {self.path}")
             return
        logger.info(f"Status notifications disabled for {self.path}")
        self._notifying = False
         # Also need to signal the change in the 'Notifying' property
        self.PropertiesChanged(self.INTERFACE_NAME, {'Notifying': GLib.Variant('b', self._notifying)}, [])

    @property
    def UUID(self): return self._uuid
    @property
    def Service(self): return self._service_path
    @property
    def Value(self): return array.array('y', self._value).tolist() # Return current value
    @property
    def Notifying(self): return self._notifying
    @property
    def Flags(self): return self._flags

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return { GATT_CHRC_IFACE: {'UUID': self._uuid, 'Service': self._service_path, 'Value': self.Value, 'Notifying': self._notifying, 'Flags': self._flags }}

    def GetAll(self, interface_name):
        if interface_name == self.INTERFACE_NAME:
            props = self.get_properties()[GATT_CHRC_IFACE]
            # pydbus needs actual values, not variants here
            return {
                'UUID': props['UUID'],
                'Service': props['Service'],
                'Value': props['Value'], # Use the property getter
                'Notifying': props['Notifying'],
                'Flags': props['Flags']
                }
        else:
            logger.error(f"GetAll called for incorrect interface: {interface_name} on {self.path}")
            raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Interface Not Found")

    def update_value(self, value_bytes):
        """ Updates internal value. Returns True if changed, False otherwise. """
        if value_bytes != self._value:
            self._value = value_bytes
            return True
        return False

    def send_notification(self):
        """ Sends a PropertiesChanged signal for the Value property. """
        if not self._notifying:
            # logger.debug(f"send_notification called on {self.path} but not notifying.")
            return False # Don't send if not notifying

        logger.info(f"Attempting to send notification for {self.path}: {self._value.decode(errors='ignore')[:50]}...")
        try:
            # Structure for PropertiesChanged signal:
            # string: Interface name
            # dict[string]variant: Changed properties (prop_name -> new_value)
            # array[string]: Invalidated properties (usually empty)
            changed_props = {'Value': GLib.Variant('ay', self.Value)} # self.Value gets the list from property
            invalidated_props = []

            # Emit the signal. This relies on the object instance being correctly
            # managed within the pydbus/GLib event loop.
            self.PropertiesChanged(self.INTERFACE_NAME, changed_props, invalidated_props)

            logger.info(f"Sent notification for {self.path} successfully.")
            return True # Indicate success or that the attempt was made
        except Exception as e:
            logger.error(f"Error sending notification for {self.path}: {e}", exc_info=True)
            return False # Indicate failure


class ScannedSSIDsCharacteristic(WifiStatusCharacteristic): # Inherits Read/Notify logic
    """ org.bluez.GattCharacteristic1 implementation for Read/Notify SSID list. """
    # __dbus_xml__ is inherited from WifiStatusCharacteristic
    INTERFACE_NAME = GATT_CHRC_IFACE # Set interface_name for base class
    # PropertiesChanged signal is inherited

    def __init__(self, path, uuid, service_path):
        # Call parent __init__ FIRST
        super().__init__(path, uuid, service_path)
        # NOW override specific properties for this characteristic
        self._flags = ['read', 'notify']
        # Initialize with the specific global state, ensuring it's bytes
        self._value = scanned_ssids_json if isinstance(scanned_ssids_json, bytes) else str(scanned_ssids_json).encode('utf-8')
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid} (SSID List)")
        self.interface_name = GATT_CHRC_IFACE # Ensure it's set correctly

    def ReadValue(self, options):
        logger.info(f"ReadValue SSIDs: {self._value.decode(errors='ignore')[:100]}...") # Log truncated value
        return array.array('y', self._value).tolist()

    # Value property uses the self._value set in __init__ via inheritance
    # get_properties uses the self._value set in __init__ via inheritance
    # GetAll uses the self._value set in __init__ via inheritance
    # update_value is inherited
    # send_notification is inherited
    # StartNotify/StopNotify are inherited


# --- D-Bus Object Manager Implementation ---
class ApplicationObjectManager(object):
    """
    org.freedesktop.DBus.ObjectManager implementation.
    Manages and exposes all GATT objects for this application.
    """
    # IMPORTANT: The __dbus_xml__ MUST be defined here for explicit registration
    __dbus_xml__ = f"""<node>
        <interface name='{DBUS_OM_IFACE}'>
            <method name='GetManagedObjects'>
                <arg type='a{{oa{{sa{{sv}}}}}}' name='object_paths_interfaces_and_properties' direction='out'/>
            </method>
            </interface>
    </node>"""
    INTERFACE_NAME = DBUS_OM_IFACE # Define for clarity

    def GetManagedObjects(self):
        """Return all objects managed by this application."""
        logger.info("GetManagedObjects called by BlueZ")
        response = {}
        # _app_objects should contain path -> object instance mapping
        # These objects are the Service and its Characteristics
        for path, obj in _app_objects.items():
            if hasattr(obj, 'get_properties'): # Check if object has our helper method
                obj_props = obj.get_properties() # Call helper method
                # The properties returned by get_properties should ALREADY be in the
                # format { interface_name: { prop_name: prop_value, ... }, ... }
                # Make sure the values are basic types, not GLib.Variant here.
                response[path] = obj_props
                logger.debug(f"  Adding object {path}: {obj_props}")
            else:
                logger.warning(f"Object at {path} lacks get_properties method")
        logger.debug(f"GetManagedObjects response: {response}")
        return response

# --- D-Bus LE Advertisement Implementation ---
class Advertisement(BluezPropertyInterface):
    """ org.bluez.LEAdvertisement1 implementation. """
    # IMPORTANT: The __dbus_xml__ MUST be defined here for explicit registration
    __dbus_xml__ = f"""<node>
        <interface name='org.bluez.LEAdvertisement1'>
            <method name='Release'/>
            <property name='Type' type='s' access='read'/>
            <property name='ServiceUUIDs' type='as' access='read'/>
            <property name='LocalName' type='s' access='read'/>
            <property name='IncludeTxPower' type='b' access='read'/>
            </interface>
        <interface name='{DBUS_PROP_IFACE}'>
            <method name='Get'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='out'/></method>
            <method name='Set'><arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='in'/></method>
            <method name='GetAll'><arg type='s' direction='in'/><arg type='a{{sv}}' direction='out'/></method>
        </interface>
    </node>"""
    INTERFACE_NAME = 'org.bluez.LEAdvertisement1'
    PATH_BASE = AD_PATH_BASE

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index); self.bus = bus; self._ad_type = advertising_type
        self._service_uuids = [SERVICE_UUID]; self._local_name = "PiWifiConfig"
        self._include_tx_power = False; self.index = index
        # Add Manufacturer/Service Data here if desired, e.g.
        # self._manufacturer_data = { 0xFFFF: GLib.Variant('ay', [0x12, 0x34]) } # Example Nordic ID
        # self._service_data = { SERVICE_UUID: GLib.Variant('ay', [0x01, 0x02]) }
        logger.info(f"Initializing Advertisement: {self.path}");
        self.interface_name = 'org.bluez.LEAdvertisement1' # Set interface_name for base class

    def Release(self):
        # This method is called by BlueZ when the advertisement is unregistered.
        # You don't typically need to do anything here unless you have specific cleanup.
        logger.info(f"Advertisement {self.path} released by BlueZ")

    @property
    def Type(self): return self._ad_type
    @property
    def ServiceUUIDs(self): return self._service_uuids
    @property
    def LocalName(self): return self._local_name
    @property
    def IncludeTxPower(self): return self._include_tx_power
    # Add properties for ManufacturerData, ServiceData if used
    # @property
    # def ManufacturerData(self): return self._manufacturer_data
    # @property
    # def ServiceData(self): return self._service_data

    def get_properties(self):
        """Return properties as dictionary"""
        # This is primarily for the GetAll method below.
        props = {
            'Type': self._ad_type,
            'ServiceUUIDs': self._service_uuids,
            'LocalName': self._local_name,
            'IncludeTxPower': self._include_tx_power,
            # Add ManufacturerData/ServiceData keys if used
            # 'ManufacturerData': self._manufacturer_data,
            # 'ServiceData': self._service_data
        }
        # Ensure the key matches the interface name in __dbus_xml__
        return {self.INTERFACE_NAME: props}


    def GetAll(self, interface_name):
        if interface_name == self.INTERFACE_NAME:
            # Get properties using the helper method
            props_dict = self.get_properties()
            # Check if the expected interface key exists
            if self.INTERFACE_NAME in props_dict:
                props = props_dict[self.INTERFACE_NAME]
                # Return basic types, not GLib.Variant
                return props
            else:
                 logger.error(f"GetAll: Interface key '{self.INTERFACE_NAME}' not found in get_properties result for {self.path}")
                 raise pydbus.dbus.DBusException("o.f.DBus.Error.Failed", "Internal error retrieving properties")
        elif interface_name == DBUS_PROP_IFACE: # Handle GetAll for Properties interface
            # This should return ALL properties for ALL interfaces the object implements,
            # but for simplicity here, we just return the main interface properties.
            # A more complete implementation would merge properties from all interfaces.
             logger.warning(f"GetAll called for DBUS_PROP_IFACE on {self.path}, returning only {self.INTERFACE_NAME} properties.")
             props_dict = self.get_properties()
             if self.INTERFACE_NAME in props_dict:
                 return props_dict[self.INTERFACE_NAME]
             else:
                 logger.error(f"GetAll: Interface key '{self.INTERFACE_NAME}' not found in get_properties result for {self.path}")
                 raise pydbus.dbus.DBusException("o.f.DBus.Error.Failed", "Internal error retrieving properties")

        else:
            logger.error(f"GetAll called for incorrect interface: {interface_name} on {self.path}")
            raise pydbus.dbus.DBusException("o.f.DBus.Error.InvalidArgs", "Interface Not Found")


# --- Helper Functions ---
def find_adapter(bus_obj):
    """Find the first available Bluetooth adapter."""
    remote_om = bus_obj.get(BLUEZ_SERVICE_NAME, '/')
    objects = remote_om.GetManagedObjects()
    for path, interfaces in objects.items():
        if ADAPTER_IFACE in interfaces.keys():
             logger.info(f"Found adapter {path}")
             return path
    logger.error("Bluetooth adapter not found in managed objects")
    return None

# --- Main Application Logic ---
def main():
    global mainloop, cmd_char, status_char, ssid_char, bus, _app_objects, advertisement, app_manager
    mainloop = GLib.MainLoop()
    bus = pydbus.SystemBus()

    # Request the service name. This is important!
    try:
        logger.info(f"Requesting D-Bus name: {APP_BUS_NAME}")
        bus.request_name(APP_BUS_NAME, allow_replacement=True)
        logger.info(f"Successfully acquired D-Bus name: {APP_BUS_NAME}")
    except Exception as e:
        logger.error(f"Failed to request D-Bus name {APP_BUS_NAME}: {e}")
        return # Cannot proceed without the bus name


    adapter_path = find_adapter(bus)
    if not adapter_path:
        logger.error("BlueZ adapter not found, exiting.")
        return

    # Get BlueZ proxy objects AFTER finding the adapter
    gatt_manager = None
    ad_manager = None
    try:
        gatt_manager = bus.get(BLUEZ_SERVICE_NAME, adapter_path)[GATT_MANAGER_IFACE]
        ad_manager = bus.get(BLUEZ_SERVICE_NAME, adapter_path)[LE_ADVERTISING_MANAGER_IFACE]
    except KeyError as e:
        logger.error(f"Failed to get BlueZ manager interface: {e}. Is Bluetooth service running and adapter powered on?")
        return
    except GLib.Error as e: # Catch GDBus errors (e.g., service not running)
        logger.error(f"GDBus Error getting BlueZ manager interface: {e}")
        return
    except Exception as e: # Catch other potential errors
        logger.error(f"Unexpected error getting BlueZ manager interface: {e}", exc_info=True)
        return


    # Instantiate ALL GATT objects FIRST
    cmd_char = WifiCommandCharacteristic(CMD_CHAR_PATH, CMD_CHAR_UUID, SERVICE_PATH)
    status_char = WifiStatusCharacteristic(STATUS_CHAR_PATH, STATUS_CHAR_UUID, SERVICE_PATH)
    ssid_char = ScannedSSIDsCharacteristic(SSID_CHAR_PATH, SSID_CHAR_UUID, SERVICE_PATH)
    service = WifiConfigService(SERVICE_PATH, SERVICE_UUID, [cmd_char, status_char, ssid_char])

    # Instantiate the Object Manager
    app_manager = ApplicationObjectManager()

    # Instantiate Advertisement object
    advertisement = Advertisement(bus, 0, 'peripheral')

    # Populate the dictionary used by ApplicationObjectManager.GetManagedObjects
    _app_objects = {
        SERVICE_PATH: service,
        CMD_CHAR_PATH: cmd_char,
        STATUS_CHAR_PATH: status_char,
        SSID_CHAR_PATH: ssid_char,
    }
    logger.info("Instantiated GATT objects and Advertisement")


    # --- *** REGISTER the necessary objects using context managers *** ---
    try:
        # Ensure the class has the __dbus_xml__ attribute defined
        if not hasattr(ApplicationObjectManager, '__dbus_xml__'):
            raise AttributeError("ApplicationObjectManager is missing __dbus_xml__ attribute")
        # REMOVED: om_node_info = Gio.DBusNodeInfo.new_for_xml(ApplicationObjectManager.__dbus_xml__)

        logger.info(f"Registering ApplicationObjectManager at {APP_OBJECT_ROOT} under {APP_BUS_NAME}")
        # Use register_object, passing the XML STRING directly
        with bus.register_object(APP_OBJECT_ROOT, app_manager, ApplicationObjectManager.__dbus_xml__): # <-- Pass XML string
            logger.info("ApplicationObjectManager registered.")

            # Ensure the class has the __dbus_xml__ attribute defined
            if not hasattr(Advertisement, '__dbus_xml__'):
                raise AttributeError("Advertisement is missing __dbus_xml__ attribute")
            # REMOVED: ad_node_info = Gio.DBusNodeInfo.new_for_xml(Advertisement.__dbus_xml__)

            logger.info(f"Registering Advertisement at {ADVERTISEMENT_PATH} under {APP_BUS_NAME}")
            # Use register_object, passing the XML STRING directly
            with bus.register_object(ADVERTISEMENT_PATH, advertisement, Advertisement.__dbus_xml__): # <-- Pass XML string
                logger.info("Advertisement registered.")

                # --- Now Register with BlueZ (INSIDE the context managers) ---
                # This ensures D-Bus objects exist when BlueZ needs them
                bluez_registered = False # Flag to track successful registration
                try:
                    logger.info(f"Registering GATT application with BlueZ (Object Manager path: {APP_OBJECT_ROOT})")
                    gatt_manager.RegisterApplication(APP_OBJECT_ROOT, {})
                    logger.info("GATT application registered successfully.")

                    logger.info(f"Registering LE advertisement with BlueZ (Advertisement path: {ADVERTISEMENT_PATH})")
                    ad_manager.RegisterAdvertisement(ADVERTISEMENT_PATH, {})
                    logger.info("Advertisement registered successfully.")
                    bluez_registered = True # Mark as successful

                    # Run the main loop (also inside the context managers)
                    logger.info("Running GLib main loop... Press Ctrl+C to exit.")
                    mainloop.run() # This will block until mainloop.quit()

                except GLib.Error as e: # Catch GDBus errors correctly
                    logger.error(f"GLib/GDBus Error during BlueZ registration or main loop: {e}", exc_info=True)
                    logger.error("Ensure Bluetooth service is running, the adapter is powered on, and the script has permissions.")
                except KeyboardInterrupt:
                     logger.info("Keyboard interrupt received.")
                except Exception as e:
                    logger.error(f"Unexpected Error during BlueZ registration or main loop: {e}", exc_info=True)
                finally:
                    # --- BlueZ Unregistration ---
                    logger.info("Initiating BlueZ unregistration...")
                    if bluez_registered: # Only try if registration succeeded
                        try:
                            logger.info("Unregistering advertisement from BlueZ...")
                            if ad_manager is not None:
                                try:
                                    ad_manager.UnregisterAdvertisement(ADVERTISEMENT_PATH)
                                    logger.info("Advertisement unregistered from BlueZ")
                                except GLib.Error as e:
                                    logger.warning(f"GLib/GDBus Error unregistering advertisement (might be expected): {e}")
                                except Exception as e_inner:
                                     logger.error(f"Unexpected error unregistering advertisement from BlueZ: {e_inner}", exc_info=True)
                            else:
                                logger.warning("Advertisement manager not available, skipping BlueZ unregistration.")
                        except Exception as e_outer:
                             logger.error(f"Error during advertisement unregistration block: {e_outer}", exc_info=True)

                        try:
                            logger.info("Unregistering GATT application from BlueZ...")
                            if gatt_manager is not None:
                                try:
                                    gatt_manager.UnregisterApplication(APP_OBJECT_ROOT)
                                    logger.info("GATT application unregistered from BlueZ")
                                except GLib.Error as e:
                                    logger.warning(f"GLib/GDBus Error unregistering application (might be expected): {e}")
                                except Exception as e_inner:
                                     logger.error(f"Unexpected error unregistering GATT application from BlueZ: {e_inner}", exc_info=True)
                            else:
                                logger.warning("GATT manager not available, skipping BlueZ unregistration.")
                        except Exception as e_outer:
                            logger.error(f"Error during GATT application unregistration block: {e_outer}", exc_info=True)
                    else:
                         logger.info("Skipping BlueZ unregistration as initial registration may not have completed.")

                    # Quit the main loop if it's still running
                    if mainloop and mainloop.is_running():
                        mainloop.quit()
                    logger.info("Exiting main loop context...")

            # This code runs after the inner 'with' block (Advertisement) exits
            logger.info("Advertisement D-Bus object unregistered.")
        # This code runs after the outer 'with' block (ObjectManager) exits
        logger.info("ApplicationObjectManager D-Bus object unregistered.")

    except AttributeError as e: # Catch missing __dbus_xml__
        logger.error(f"Configuration Error: {e}", exc_info=True)
    except GLib.Error as e: # Catch errors during D-Bus object registration itself
        logger.error(f"GLib.Error during D-Bus object registration: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to register objects on D-Bus: {e}", exc_info=True)
    finally:
        # Final cleanup message
        logger.info("Script finished.")


if __name__ == '__main__':
    main()
