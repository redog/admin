#!/usr/bin/python3
# -*- coding:utf-8 -*-

import sys
import logging
import array
import subprocess

# D-Bus / GLib related imports
import pydbus
# Removed: from pydbus.publication import Publication
from gi.repository import GLib

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
    __dbus_xml__ = f"""
    <node>
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
    </node>
    """
    INTERFACE_NAME = GATT_SERVICE_IFACE

    def __init__(self, path, uuid, characteristics):
        self.path = path; self._uuid = uuid; self._primary = True
        self._characteristics_instances = characteristics
        self._characteristics_paths = [c.path for c in characteristics]
        logger.info(f"Initializing Service: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_SERVICE_IFACE

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
            return {k: GLib.Variant(sig, val) for k, (sig, val) in {
                'UUID': ('s', self._uuid),
                'Primary': ('b', self._primary),
                'Characteristics': ('ao', self._characteristics_paths)
            }.items()}
        else: return super().GetAll(interface_name)

# --- D-Bus GATT Characteristic Implementations ---
CHARACTERISTIC_DBUS_XML = f"""
<node>
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
</node>
"""

class WifiCommandCharacteristic(BluezPropertyInterface):
    """ org.bluez.GattCharacteristic1 implementation for Write commands. """
    __dbus_xml__ = CHARACTERISTIC_DBUS_XML
    INTERFACE_NAME = GATT_CHRC_IFACE

    def __init__(self, path, uuid, service_path):
        self.path = path; self._uuid = uuid; self._service_path = service_path
        self._flags = ['write', 'write-without-response']
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_CHRC_IFACE

    def ReadValue(self, options): raise pydbus.dbus.DBusException("org.bluez.Error.NotPermitted", "Read not permitted")
    def WriteValue(self, value, options):
        command = bytes(value).decode('utf-8').strip()
        logger.info(f"WriteValue called: {command}")
        GLib.idle_add(self.handle_command, command, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def handle_command(self, command):
        # (Command handling logic - truncated)
        logger.info(f"Handling command: {command}")
        global current_status, scanned_ssids_json, status_char, ssid_char
        new_status = None; new_ssids = None; state_changed = False; ssid_state_changed = False
        # ... (Scan/Connect logic using subprocess) ...
        if command.upper() == "SCAN":
            new_status = b"Scanning..."; logger.info("Scan...") # Simplified placeholder
            # Simulate finding networks
            new_ssids = b'["NetA", "NetB"]'
            GLib.timeout_add_seconds(2, lambda: self.update_scan_result(new_ssids)) # Simulate delay
        elif command.upper().startswith("CONNECT"):
             new_status = b"Connecting..."; logger.info("Connect...") # Simplified placeholder
             # Simulate connection result
             GLib.timeout_add_seconds(3, lambda: self.update_connection_result(b"Connected"))
        else: new_status = b"Error: Unknown"; logger.warning(f"Unknown command: {command}")

        if new_status is not None and new_status != current_status: current_status = new_status; state_changed = True; logger.info(f"Status -> {current_status.decode()}")

        if state_changed and status_char: GLib.idle_add(status_char.send_notification)
        # Notify for SSIDs happens in callback update_scan_result
        return False # Remove idle source

    def update_scan_result(self, result_ssids_bytes):
        """Callback to update status and SSIDs after scan"""
        global current_status, scanned_ssids_json, status_char, ssid_char
        logger.info(f"Updating scan results: {result_ssids_bytes.decode()}")
        current_status = b"Scan Complete"
        scanned_ssids_json = result_ssids_bytes
        if status_char:
            status_char.update_value(current_status)
            GLib.idle_add(status_char.send_notification)
        if ssid_char:
            ssid_char.update_value(scanned_ssids_json)
            GLib.idle_add(ssid_char.send_notification)
        return False

    def update_connection_result(self, result_status_bytes):
        """Callback to update status after simulated connection"""
        global current_status, status_char
        logger.info(f"Updating connection status to: {result_status_bytes.decode()}")
        current_status = result_status_bytes
        if status_char:
            status_char.update_value(current_status)
            GLib.idle_add(status_char.send_notification)
        return False

    def StartNotify(self): raise pydbus.dbus.DBusException("org.bluez.Error.NotSupported", "Notify not supported")
    def StopNotify(self): pass

    @property
    def UUID(self): return self._uuid
    @property
    def Service(self): return self._service_path
    @property
    def Value(self): return []
    @property
    def Notifying(self): return False
    @property
    def Flags(self): return self._flags

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return { GATT_CHRC_IFACE: {'UUID': self._uuid, 'Service': self._service_path, 'Value': [], 'Notifying': False, 'Flags': self._flags }}

    def GetAll(self, interface_name):
         if interface_name == self.INTERFACE_NAME:
             props = self.get_properties()[GATT_CHRC_IFACE]
             return {k: GLib.Variant(sig, val) for k, (sig, val) in {'UUID': ('s', props['UUID']), 'Service': ('o', props['Service']), 'Value': ('ay', props['Value']), 'Notifying': ('b', props['Notifying']), 'Flags': ('as', props['Flags'])}.items()}
         else: return super().GetAll(interface_name)


class WifiStatusCharacteristic(BluezPropertyInterface):
    """ org.bluez.GattCharacteristic1 implementation for Read/Notify status. """
    __dbus_xml__ = CHARACTERISTIC_DBUS_XML
    INTERFACE_NAME = GATT_CHRC_IFACE

    def __init__(self, path, uuid, service_path):
        self.path = path; self._uuid = uuid; self._service_path = service_path
        self._flags = ['read', 'notify']; self._notifying = False
        self._value = current_status
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid}")
        self.interface_name = GATT_CHRC_IFACE

    def ReadValue(self, options): logger.info(f"ReadValue Status: {self._value.decode()}"); return array.array('y', self._value).tolist()
    def WriteValue(self, v, o): raise pydbus.dbus.DBusException("org.bluez.Error.WriteNotPermitted", "Write not permitted")
    def StartNotify(self): logger.info("Status notifications enabled"); self._notifying = True
    def StopNotify(self): logger.info("Status notifications disabled"); self._notifying = False

    @property
    def UUID(self): return self._uuid
    @property
    def Service(self): return self._service_path
    @property
    def Value(self): return array.array('y', self._value).tolist()
    @property
    def Notifying(self): return self._notifying
    @property
    def Flags(self): return self._flags

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return { GATT_CHRC_IFACE: {'UUID': self._uuid, 'Service': self._service_path, 'Value': array.array('y', self._value).tolist(), 'Notifying': self._notifying, 'Flags': self._flags }}

    def GetAll(self, interface_name):
         if interface_name == self.INTERFACE_NAME:
             props = self.get_properties()[GATT_CHRC_IFACE]
             return {k: GLib.Variant(sig, val) for k, (sig, val) in {'UUID': ('s', props['UUID']), 'Service': ('o', props['Service']), 'Value': ('ay', props['Value']), 'Notifying': ('b', props['Notifying']), 'Flags': ('as', props['Flags'])}.items()}
         else: return super().GetAll(interface_name)

    def update_value(self, value_bytes):
        if value_bytes != self._value: self._value = value_bytes; return True
        return False

    def send_notification(self):
        if not self._notifying: return False
        try:
            props_changed_args = ( self.INTERFACE_NAME, {'Value': GLib.Variant('ay', self.Value)}, [])
            # Emit signal - Requires the object to be published/exported correctly
            # This might need adjustment depending on how pydbus handles signals without Publication
            # Let's assume for now the object can emit its own signals if kept alive by main loop
            self.PropertiesChanged(*props_changed_args)
            logger.info(f"Sent status notification: {self._value.decode(errors='ignore')}")
            return True
        except Exception as e: logger.error(f"Error sending status notification: {e}"); return False


class ScannedSSIDsCharacteristic(WifiStatusCharacteristic): # Inherits Read/Notify logic
    """ org.bluez.GattCharacteristic1 implementation for Read/Notify SSID list. """
    __dbus_xml__ = CHARACTERISTIC_DBUS_XML
    INTERFACE_NAME = GATT_CHRC_IFACE

    def __init__(self, path, uuid, service_path):
        super().__init__(path, uuid, service_path)
        self._flags = ['read', 'notify']
        self._value = scanned_ssids_json # Use specific global state
        logger.info(f"Initializing Char: {self.path} UUID: {self._uuid} (SSID List)")
        self.interface_name = GATT_CHRC_IFACE

    def ReadValue(self, options): logger.info(f"ReadValue SSIDs: {self._value.decode()}"); return array.array('y', self._value).tolist()
    @property
    def Value(self): return array.array('y', self._value).tolist()

    def get_properties(self):
        """Return properties as dictionary for ObjectManager"""
        return { GATT_CHRC_IFACE: {'UUID': self._uuid, 'Service': self._service_path, 'Value': array.array('y', self._value).tolist(), 'Notifying': self._notifying, 'Flags': self._flags }}

    def GetAll(self, interface_name): return super().GetAll(interface_name)
    # Inherits update_value and send_notification


# --- D-Bus Object Manager Implementation ---
class ApplicationObjectManager(object):
    """
    org.freedesktop.DBus.ObjectManager implementation.
    Manages and exposes all GATT objects for this application.
    """
    __dbus_xml__ = f"""
    <node>
        <interface name='{DBUS_OM_IFACE}'>
            <method name='GetManagedObjects'>
                <arg type='a{{oa{{sa{{sv}}}}}}' name='object_paths_interfaces_and_properties' direction='out'/>
            </method>
            <signal name='InterfacesAdded'>
                <arg type='o' name='object_path'/>
                <arg type='a{{sa{{sv}}}}' name='interfaces_and_properties'/>
            </signal>
            <signal name='InterfacesRemoved'>
                <arg type='o' name='object_path'/>
                <arg type='as' name='interfaces'/>
            </signal>
        </interface>
    </node>
    """

    def GetManagedObjects(self):
        """Return all objects managed by this application."""
        logger.info("GetManagedObjects called by BlueZ")
        response = {}
        # _app_objects should contain path -> object instance mapping
        for path, obj in _app_objects.items():
            if path == APP_OBJECT_ROOT: continue # Exclude self
            if hasattr(obj, 'get_properties'): # Check if object has our helper method
                 obj_props = obj.get_properties() # Call helper method
                 response[path] = obj_props
                 logger.debug(f"  Adding object {path}: {obj_props}")
            else:
                 logger.warning(f"Object at {path} lacks get_properties method")
        return response

# --- D-Bus LE Advertisement Implementation ---
class Advertisement(BluezPropertyInterface):
    """ org.bluez.LEAdvertisement1 implementation. """
    __dbus_xml__ = f"""
    <node>
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
    </node>
    """
    INTERFACE_NAME = 'org.bluez.LEAdvertisement1'
    PATH_BASE = AD_PATH_BASE

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index); self.bus = bus; self._ad_type = advertising_type
        self._service_uuids = [SERVICE_UUID]; self._local_name = "PiWifiConfig"
        self._include_tx_power = False; self.index = index
        logger.info(f"Initializing Advertisement: {self.path}"); self.interface_name = 'org.bluez.LEAdvertisement1'

    def Release(self): logger.info(f"Advertisement {self.path} released")

    @property
    def Type(self): return self._ad_type
    @property
    def ServiceUUIDs(self): return self._service_uuids
    @property
    def LocalName(self): return self._local_name
    @property
    def IncludeTxPower(self): return self._include_tx_power

    def get_properties(self):
         """Return properties as dictionary"""
         # Note: This object doesn't need to be returned by ApplicationObjectManager
         # but defining this for consistency if needed elsewhere.
         return {
             'org.bluez.LEAdvertisement1': {
                 'Type': self._ad_type,
                 'ServiceUUIDs': self._service_uuids,
                 'LocalName': self._local_name,
                 'IncludeTxPower': self._include_tx_power
             }
         }

    def GetAll(self, interface_name):
        if interface_name == self.INTERFACE_NAME:
            props = self.get_properties()['org.bluez.LEAdvertisement1']
            return {k: GLib.Variant(sig, val) for k, (sig, val) in {
                'Type': ('s', props['Type']),
                'ServiceUUIDs': ('as', props['ServiceUUIDs']),
                'LocalName': ('s', props['LocalName']),
                'IncludeTxPower': ('b', props['IncludeTxPower'])
            }.items()}
        else: return super().GetAll(interface_name)


# --- Helper Functions ---
def find_adapter(bus_obj):
    """Find the first available Bluetooth adapter."""
    remote_om = bus_obj.get(BLUEZ_SERVICE_NAME, '/')
    objects = remote_om.GetManagedObjects()
    for path, interfaces in objects.items():
        if ADAPTER_IFACE in interfaces.keys(): logger.info(f"Found adapter {path}"); return path
    return None

# --- Main Application Logic ---
def register_app_cb(): logger.info("GATT application registered successfully.")
def register_app_error_cb(error): logger.error(f"Failed to register application: {error}"); mainloop and mainloop.quit()
def register_ad_cb(): logger.info("Advertisement registered successfully.")
def register_ad_error_cb(error): logger.error(f"Failed to register advertisement: {error}"); mainloop and mainloop.quit()

def main():
    global mainloop, cmd_char, status_char, ssid_char, bus, _published_objects, advertisement, app_manager
    mainloop = GLib.MainLoop()
    bus = pydbus.SystemBus()

    adapter_path = find_adapter(bus)
    if not adapter_path: logger.error("BlueZ adapter not found"); return

    gatt_manager = bus.get(BLUEZ_SERVICE_NAME, adapter_path)[GATT_MANAGER_IFACE]
    ad_manager = bus.get(BLUEZ_SERVICE_NAME, adapter_path)[LE_ADVERTISING_MANAGER_IFACE]

    # Instantiate ALL GATT objects
    cmd_char = WifiCommandCharacteristic(CMD_CHAR_PATH, CMD_CHAR_UUID, SERVICE_PATH)
    status_char = WifiStatusCharacteristic(STATUS_CHAR_PATH, STATUS_CHAR_UUID, SERVICE_PATH)
    ssid_char = ScannedSSIDsCharacteristic(SSID_CHAR_PATH, SSID_CHAR_UUID, SERVICE_PATH)
    service = WifiConfigService(SERVICE_PATH, SERVICE_UUID, [cmd_char, status_char, ssid_char])

    # Instantiate the Object Manager
    app_manager = ApplicationObjectManager()

    # Instantiate Advertisement object
    advertisement = Advertisement(bus, 0, 'peripheral')

    # Store all GATT objects that need to be exposed via the ObjectManager
    _app_objects = {
        SERVICE_PATH: service,
        CMD_CHAR_PATH: cmd_char,
        STATUS_CHAR_PATH: status_char,
        SSID_CHAR_PATH: ssid_char,
    }
    logger.info("Instantiated GATT objects and Advertisement")

    # --- NO EXPLICIT PUBLICATION ---
    # We rely on the objects being kept alive and BlueZ finding them via introspection
    # on our connection when RegisterApplication/RegisterAdvertisement is called.

    # Register Application and Advertisement with BlueZ
    try:
        logger.info("Registering GATT application...")
        gatt_manager.RegisterApplication(
            APP_OBJECT_ROOT, {} # Path to the Object Manager (BlueZ expects this)
                                # BlueZ will call GetManagedObjects on the object at this path
        )
        register_app_cb()

        logger.info("Registering LE advertisement...")
        # We still need to tell BlueZ about the Advertisement object.
        # Does it need to be published? Let's try without first.
        # If this fails with "No object received", we might need to publish ONLY the Ad object.
        ad_manager.RegisterAdvertisement(
            ADVERTISEMENT_PATH, {} # Path where BlueZ expects the Ad object
        )
        register_ad_cb()

    except GLib.Error as e: # Catch GDBus errors correctly
        logger.error(f"GLib/GDBus Error during BlueZ registration: {e}")
        # Attempt cleanup even if registration failed partially
        try: ad_manager.UnregisterAdvertisement(ADVERTISEMENT_PATH)
        except: pass # Ignore errors during cleanup
        try: gatt_manager.UnregisterApplication(APP_OBJECT_ROOT)
        except: pass # Ignore errors during cleanup
        return
    except Exception as e:
         logger.error(f"Unexpected Error during BlueZ registration: {e}")
         # Attempt cleanup
         try: ad_manager.UnregisterAdvertisement(ADVERTISEMENT_PATH)
         except: pass
         try: gatt_manager.UnregisterApplication(APP_OBJECT_ROOT)
         except: pass
         return


    # Run the main loop
    try:
        logger.info("Running GLib main loop...")
        mainloop.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received.")
    finally:
        logger.info("Unregistering advertisement and application...")
        try:
            ad_manager.UnregisterAdvertisement(ADVERTISEMENT_PATH)
            logger.info("Advertisement unregistered")
        except Exception as e: logger.error(f"Error unregistering advertisement: {e}")
        try:
            gatt_manager.UnregisterApplication(APP_OBJECT_ROOT)
            logger.info("GATT application unregistered")
        except Exception as e: logger.error(f"Error unregistering application: {e}")

        logger.info("Exiting.")

if __name__ == '__main__':
    main()
