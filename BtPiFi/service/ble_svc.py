#!/usr/bin/env python3

import asyncio
import dbus_next.aio
from dbus_next import BusType, Variant, DBusError
# Import ServiceInterface, method, dbus_property, PropertyAccess
from dbus_next.service import ServiceInterface, method, dbus_property, PropertyAccess
import subprocess
import json
# Removed ThreadPoolExecutor as it's handled by run_in_executor
import traceback
import time # Import the time module for sleep
import sys # For reading sys files
import os # For checking root privileges

# --- Configuration ---
APP_PATH = "/com/automationwise/btpifi"
SERVICE_PATH = APP_PATH + "/service0"
# Characteristic Paths
CHAR_RW_PATH = SERVICE_PATH + "/char0"    # Read/Write Char
CHAR_SCAN_PATH = SERVICE_PATH + "/char1"  # WiFi Scan Char
CHAR_SSID_PATH = SERVICE_PATH + "/char2"  # Set SSID Char
CHAR_PSK_PATH = SERVICE_PATH + "/char3"   # Set PSK Char
# Connect Trigger Characteristic (Assuming you'll add this later if needed)
# CHAR_CONNECT_PATH = SERVICE_PATH + "/char4"
# Descriptor Paths
DESC_RW_PATH = CHAR_RW_PATH + "/desc0"
DESC_SCAN_PATH = CHAR_SCAN_PATH + "/desc0"
DESC_SSID_PATH = CHAR_SSID_PATH + "/desc0"
DESC_PSK_PATH = CHAR_PSK_PATH + "/desc0"
# DESC_CONNECT_PATH = CHAR_CONNECT_PATH + "/desc0"
# Advertisement Path (Using a distinct base for advertisement object)
ADVERTISEMENT_PATH = "/com/automationwise/btpifi/advertisement0"


# Service UUID
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
# Characteristic UUIDs
CHAR_READ_WRITE_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"
WIFI_SCAN_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"
WIFI_SET_SSID_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"
WIFI_SET_PSK_UUID = "133934e4-01f5-4054-a88f-0136e064c49e"
# WIFI_CONNECT_UUID = "133934e5-01f5-4054-a88f-0136e064c49e" # If you add connect trigger
# Descriptor UUID
USER_DESC_UUID = "2901" # Characteristic User Description

# Default Device Name (Used if MAC cannot be read)
DEFAULT_DEVICE_NAME = "BtPiFi-Setup"
# WiFi Interface Name (Adjust if different, e.g., 'wlan1')
WIFI_INTERFACE = "wlan0"


# BlueZ & D-Bus Constants
BLUEZ_SERVICE = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE =      'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE =    'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE =    'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE =    'org.bluez.GattDescriptor1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'


# --- Helper Functions ---

def get_dynamic_device_name(interface: str, default_name: str) -> str:
    """
    Generates a device name like 'BtPiFi-XXXX' using the last 2 bytes
    of the specified network interface's MAC address.
    Falls back to default_name if the MAC cannot be read.
    """
    mac_path = f"/sys/class/net/{interface}/address"
    try:
        with open(mac_path, 'r') as f:
            mac_address = f.readline().strip()
        # MAC format: aa:bb:cc:dd:ee:ff
        if len(mac_address) == 17 and mac_address.count(':') == 5:
            # Remove colons and take last 4 chars (last 2 bytes)
            mac_suffix = mac_address.replace(":", "")[-4:].upper()
            device_name = f"BtPiFi-{mac_suffix}"
            print(f"Using dynamic device name: {device_name} (from {interface} MAC: {mac_address})")
            return device_name
        else:
            print(f"Warning: Could not parse MAC address '{mac_address}' from {mac_path}.")
    except FileNotFoundError:
        print(f"Warning: Could not find MAC address file: {mac_path}. Interface '{interface}' down or doesn't exist?")
    except Exception as e:
        print(f"Warning: Error reading MAC address from {mac_path}: {e}")

    print(f"Falling back to default device name: {default_name}")
    return default_name


# (run_wifi_scan function remains the same as provided by user)
def run_wifi_scan():
    ssids = []
    try:
        rescan_cmd = ["sudo", "nmcli", "dev", "wifi", "rescan"]
        print(f"Running command: {' '.join(rescan_cmd)}")
        subprocess.run(rescan_cmd, check=True, timeout=15, capture_output=True) # Increased timeout
        scan_wait_time = 8
        print(f"Waiting {scan_wait_time} seconds for scan results...")
        time.sleep(scan_wait_time)
        list_cmd = ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list"]
        print(f"Running command: {' '.join(list_cmd)}")
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True, timeout=10)
        output = result.stdout.strip()
        print(f"Scan output:\n{output}")
        if output:
            found_ssids = set(filter(None, output.split('\n')))
            ssids = sorted(list(found_ssids))
    except FileNotFoundError:
        print("Error: nmcli not found")
        return {"error": "nmcli not found"}
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr.strip() if e.stderr else "No stderr output"
        print(f"Error running nmcli: {e}\nStderr: {stderr_output}")
        if "wifi is disabled" in stderr_output.lower(): return {"error": "WiFi is disabled"}
        if "NetworkManager is not running" in stderr_output: return {"error": "NetworkManager is not running"}
        return {"error": f"nmcli failed: {stderr_output[:150]}"} # Show more stderr
    except subprocess.TimeoutExpired as e:
        cmd_name = 'rescan' if e.cmd == rescan_cmd else 'list'
        print(f"Error: nmcli {cmd_name} command timed out.")
        return {"error": f"WiFi {cmd_name} timed out"}
    except Exception as e:
        print(f"An unexpected error occurred during WiFi scan: {e}")
        traceback.print_exc() # Print traceback for unexpected errors
        return {"error": f"Unexpected scan error: {str(e)}"}
    print(f"Found SSIDs: {ssids}")
    return {"ssids": ssids}

# --- D-Bus Object Implementations ---
# Using the structure from the user-provided working script

class Application(ServiceInterface):
    """
    Implementation of the org.freedesktop.DBus.ObjectManager interface.
    This is exported at the application's root path (APP_PATH).
    BlueZ uses this to discover all GATT objects provided by the application.
    """
    def __init__(self, bus, app_path):
        super().__init__(DBUS_OM_IFACE)
        self.bus = bus
        self.app_path = app_path # The path where this Application object itself is exported
        # Dictionary to hold all GATT objects {ObjectPath: Instance}
        self.managed_gatt_objects = {}

    def add_gatt_object(self, path, instance):
        """Registers a GATT object (Service, Characteristic, Descriptor)"""
        print(f"DEBUG: Adding object to Application manager: {path}")
        self.managed_gatt_objects[path] = instance

    def remove_gatt_object(self, path):
        """Removes a GATT object"""
        if path in self.managed_gatt_objects:
            print(f"DEBUG: Removing object from Application manager: {path}")
            del self.managed_gatt_objects[path]

    def _get_gatt_object_properties(self, instance):
        """Helper to extract GATT properties for GetManagedObjects"""
        props = {}
        if isinstance(instance, BleService):
            props['UUID'] = Variant('s', instance.uuid)
            props['Primary'] = Variant('b', instance.primary)
            props['Characteristics'] = Variant('ao', instance.characteristic_paths)
            # Note: BlueZ might also expect 'Includes' if supporting included services
        elif isinstance(instance, BleCharacteristic):
            props['UUID'] = Variant('s', instance.uuid)
            props['Flags'] = Variant('as', instance.flags)
            props['Service'] = Variant('o', instance.service_path)
            props['Descriptors'] = Variant('ao', instance.descriptor_paths)
            # Notifying property is handled by BlueZ based on flags and StartNotify calls
        elif isinstance(instance, BleDescriptor):
            props['UUID'] = Variant('s', instance.uuid)
            props['Flags'] = Variant('as', instance.flags)
            props['Characteristic'] = Variant('o', instance.characteristic_path)
        return props

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        """
        D-Bus method called by BlueZ to discover all GATT objects.
        Returns: Dict[ObjectPath, Dict[InterfaceName, Dict[PropertyName, Variant]]]
        """
        print(f"DEBUG: GetManagedObjects called on {self.app_path}")
        managed_objects_dict = {}
        for path, instance in self.managed_gatt_objects.items():
            iface_name = None
            if isinstance(instance, BleService):
                iface_name = GATT_SERVICE_IFACE
            elif isinstance(instance, BleCharacteristic):
                iface_name = GATT_CHRC_IFACE
            elif isinstance(instance, BleDescriptor):
                iface_name = GATT_DESC_IFACE
            else:
                print(f"Warning: GetManagedObjects skipping non-GATT object at path {path}")
                continue

            gatt_props = self._get_gatt_object_properties(instance)
            if iface_name and gatt_props:
                # Structure: { Path: { Interface: { Property: Variant } } }
                managed_objects_dict[path] = { iface_name: gatt_props }
            elif iface_name:
                print(f"Warning: Could not get properties for object at {path} (Interface: {iface_name})")
                # Return empty properties dict for the interface if needed?
                # managed_objects_dict[path] = { iface_name: {} }

        print(f"DEBUG: GetManagedObjects returning dict with {len(managed_objects_dict)} GATT object paths.")
        if not managed_objects_dict:
            print("WARNING: GetManagedObjects returning empty dict. No GATT objects added?")
        # print(f"DEBUG Full GetManagedObjects dict: {managed_objects_dict}") # Very verbose
        return managed_objects_dict

class BleService(ServiceInterface):
    """Represents the GATT Service."""
    # PATH is set during instantiation
    def __init__(self, path: str, uuid: str, primary: bool):
        super().__init__(GATT_SERVICE_IFACE)
        self.PATH = path
        self.uuid = uuid
        self.primary = primary
        self.characteristic_paths = []
        # Add attributes to store WiFi credentials received via BLE
        self._target_ssid = None
        self._target_psk = None

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's': return self.uuid
    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> 'b': return self.primary
    @dbus_property(access=PropertyAccess.READ)
    def Characteristics(self) -> 'ao': return self.characteristic_paths

    def add_characteristic_path(self, path: str):
        if path not in self.characteristic_paths:
            self.characteristic_paths.append(path)

class BleCharacteristic(ServiceInterface):
    """Base class for GATT Characteristics."""
    # PATH is set during instantiation
    def __init__(self, path: str, interface_name: str, uuid: str, flags: list[str], service_path: str):
        super().__init__(interface_name) # Should be GATT_CHRC_IFACE
        self.PATH = path
        self.uuid = uuid
        self.flags = flags
        self.service_path = service_path
        self.descriptor_paths = []
        self._value = bytearray()
        self._notifying = False # Track notification status

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's': return self.uuid
    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> 'as': return self.flags
    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> 'o': return self.service_path
    @dbus_property(access=PropertyAccess.READ)
    def Descriptors(self) -> 'ao': return self.descriptor_paths
    # Notifying property is read by BlueZ, not typically defined here explicitly
    # unless you need custom logic beyond Start/StopNotify flags.

    def add_descriptor_path(self, path: str):
        if path not in self.descriptor_paths: self.descriptor_paths.append(path)

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f"Default ReadValue called for {self.uuid} at {self.PATH}. Override in subclass.")
        if 'read' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        offset = options.get('offset', Variant('q', 0)).value
        return bytes(self._value[offset:])

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for {self.uuid} at {self.PATH}. Override in subclass.")
        can_write = 'write' in self.flags or 'write-without-response' in self.flags
        if not can_write: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        offset = options.get('offset', Variant('q', 0)).value
        new_value_bytes = bytes(value)
        required_len = offset + len(new_value_bytes)
        if required_len > len(self._value):
             self._value.extend(b'\x00' * (required_len - len(self._value)))
        self._value[offset:required_len] = new_value_bytes
        self._value = self._value[:required_len] # Trim
        print(f"Wrote {len(value)} bytes at offset {offset}.")

    @method()
    async def StartNotify(self):
        print(f"StartNotify called for {self.uuid} at {self.PATH}")
        if 'notify' not in self.flags:
            raise DBusError('org.bluez.Error.NotSupported', 'Notify not supported')
        if self._notifying:
            print(" Already notifying")
            return
        self._notifying = True
        print(" Notifications started")

    @method()
    async def StopNotify(self):
        print(f"StopNotify called for {self.uuid} at {self.PATH}")
        if 'notify' not in self.flags:
             raise DBusError('org.bluez.Error.NotSupported', 'Notify not supported')
        if not self._notifying:
            print(" Not notifying")
            return
        self._notifying = False
        print(" Notifications stopped")

class BleDescriptor(ServiceInterface):
    """Base class for GATT Descriptors."""
    # PATH is set during instantiation
    def __init__(self, path: str, interface_name: str, uuid: str, flags: list[str], characteristic_path: str):
        super().__init__(interface_name) # Should be GATT_DESC_IFACE
        self.PATH = path
        self.uuid = uuid
        self.flags = flags
        self.characteristic_path = characteristic_path
        self._value = bytearray()

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's': return self.uuid
    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> 'as': return self.flags
    @dbus_property(access=PropertyAccess.READ)
    def Characteristic(self) -> 'o': return self.characteristic_path

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f"Default ReadValue called for Descriptor {self.uuid} at {self.PATH}. Override if needed.")
        if 'read' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        offset = options.get('offset', Variant('q', 0)).value
        return bytes(self._value[offset:])

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for Descriptor {self.uuid} at {self.PATH}. Override if needed.")
        if 'write' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        offset = options.get('offset', Variant('q', 0)).value
        new_value_bytes = bytes(value)
        required_len = offset + len(new_value_bytes)
        if required_len > len(self._value):
             self._value.extend(b'\x00' * (required_len - len(self._value)))
        self._value[offset:required_len] = new_value_bytes
        self._value = self._value[:required_len] # Trim
        print(f"Wrote {len(value)} bytes to descriptor at offset {offset}.")

# --- Application Specific Characteristic Implementations ---

class ReadWriteCharacteristicImpl(BleCharacteristic):
    """Simple Read/Write characteristic."""
    # PATH is passed during instantiation
    def __init__(self, path: str, service_path: str):
        super().__init__(path, GATT_CHRC_IFACE, CHAR_READ_WRITE_UUID, ["read", "write"], service_path)
        self._value = bytearray("Initial Value", "utf-8")

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> ReadWriteCharacteristicImpl.ReadValue called for {self.PATH}")
        print(f"    Sending value: {self._value.decode('utf-8', errors='replace')}")
        return await super().ReadValue(options) # Use base for offset

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f">>> ReadWriteCharacteristicImpl.WriteValue called for {self.PATH}")
        try:
            received_string = bytes(value).decode("utf-8")
            print(f"    Client WRITE received. New value: {received_string}")
            # Use base WriteValue to handle offset and update self._value
            await super().WriteValue(value, options)
        except UnicodeDecodeError:
            print("    Error (RW Char): Received invalid UTF-8 data.")
            # Decide if error should be raised
            # raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 data')

class WifiScanCharacteristicImpl(BleCharacteristic):
    """Read-only characteristic for WiFi scan results."""
    # PATH is passed during instantiation
    def __init__(self, path: str, service_path: str):
        super().__init__(path, GATT_CHRC_IFACE, WIFI_SCAN_UUID, ["read"], service_path)
        # No initial value needed, generated on read

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> WifiScanCharacteristicImpl.ReadValue called for {self.PATH}")
        print("    Client READ received (WiFi Scan Char). Starting scan...")
        loop = asyncio.get_running_loop()
        try:
            # Run blocking scan in executor
            scan_result_dict = await loop.run_in_executor(None, run_wifi_scan)
            result_json = json.dumps(scan_result_dict)
            print(f"    Sending scan result: {result_json}")
            # Store result in _value for base ReadValue to handle offset
            self._value = bytearray(result_json, "utf-8")
            return await super().ReadValue(options)
        except Exception as e:
            print(f"    Error processing scan result in ReadValue: {e}")
            traceback.print_exc()
            error_result = json.dumps({"error": f"Failed to process scan: {str(e)}"})
            self._value = bytearray(error_result, "utf-8")
            return await super().ReadValue(options) # Return error via base method

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         # Override base WriteValue to explicitly forbid writes
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted on read-only characteristic')


class SetSsidCharacteristicImpl(BleCharacteristic):
    """Write-only characteristic to receive target WiFi SSID."""
    # PATH is passed during instantiation
    def __init__(self, path: str, service: BleService): # Takes service instance
        super().__init__(path, GATT_CHRC_IFACE, WIFI_SET_SSID_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f">>> SetSsidCharacteristicImpl.WriteValue called for {self.PATH}")
        try:
            # Decode SSID as UTF-8
            ssid = bytes(value).decode("utf-8")
            if len(value) > 32: # Max SSID length in bytes
                 print(f"    Error: Received SSID is too long ({len(value)} bytes).")
                 raise DBusError('org.bluez.Error.InvalidValueLength', 'SSID too long (max 32 bytes)')
            print(f"    Received target SSID: {ssid}")
            # Store it on the service object
            self.service._target_ssid = ssid
            # Update internal _value if needed, though it's write-only
            # self._value = bytearray(value)
        except UnicodeDecodeError:
            print("    Error: Received invalid UTF-8 data for SSID.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for SSID')
        except Exception as e:
            print(f"    Error processing SSID write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process SSID: {e}')

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        # Override base ReadValue to explicitly forbid reads
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted on write-only characteristic')


class SetPskCharacteristicImpl(BleCharacteristic):
    """Write-only characteristic to receive target WiFi PSK (Password)."""
    # SECURITY WARNING: Sending PSK over unencrypted BLE is insecure!
    # PATH is passed during instantiation
    def __init__(self, path: str, service: BleService): # Takes service instance
        super().__init__(path, GATT_CHRC_IFACE, WIFI_SET_PSK_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f">>> SetPskCharacteristicImpl.WriteValue called for {self.PATH}")
        try:
            # Decode PSK as UTF-8 (WPA PSKs are typically printable strings)
            psk = bytes(value).decode("utf-8")
            psk_len = len(psk)
            psk_byte_len = len(value)
            is_hex = psk_len == 64 and all(c in '0123456789abcdefABCDEF' for c in psk)
            if psk_byte_len > 0 and not is_hex and (psk_len < 8 or psk_len > 63):
                 print(f"    Error: Received PSK has invalid length ({psk_len}). Must be 0, 8-63 chars, or 64 hex.")
                 raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid PSK length')
            print(f"    Received target PSK (length={psk_len})") # Avoid printing actual PSK
            # Store it on the service object
            self.service._target_psk = psk
            # Update internal _value if needed
            # self._value = bytearray(value)
        except UnicodeDecodeError:
            print("    Error: Received invalid UTF-8 data for PSK.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for PSK')
        except Exception as e:
            print(f"    Error processing PSK write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process PSK: {e}')

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        # Override base ReadValue to explicitly forbid reads
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted on write-only characteristic')

# --- Application Specific Descriptors ---
class UserDescriptionDescriptorImpl(BleDescriptor):
    """Read-only User Description Descriptor."""
    # PATH is passed during instantiation
    def __init__(self, path: str, description: str, characteristic_path: str):
        super().__init__(path, GATT_DESC_IFACE, USER_DESC_UUID, ["read"], characteristic_path)
        self._value = bytearray(description, "utf-8")
        # Path is passed in constructor

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> UserDescriptionDescriptorImpl.ReadValue called for {self.PATH}")
        return await super().ReadValue(options) # Use base for offset

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         # Override base WriteValue to explicitly forbid writes
         raise DBusError('org.bluez.Error.WriteNotPermitted', 'Write not permitted on read-only descriptor') # More specific error

# --- Advertising Implementation ---
class BleAdvertisement(ServiceInterface):
    """Represents the BLE Advertisement object."""
    # PATH is passed during instantiation
    def __init__(self, path: str, ad_type: str, local_name: str, service_uuids: list[str], appearance: int):
        super().__init__(LE_ADVERTISEMENT_IFACE)
        self.PATH = path
        self.type = ad_type
        self.local_name = local_name
        self.service_uuids = service_uuids
        self.appearance = appearance
        # Add other Ad properties here if needed (e.g., IncludeTxPower=True)

    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> 's': return self.type
    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> 's': return self.local_name
    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> 'as': return self.service_uuids
    @dbus_property(access=PropertyAccess.READ)
    def Appearance(self) -> 'q': return self.appearance # uint16

    @method()
    def Release(self):
        """Called by BlueZ when advertisement is unregistered."""
        print(f"Advertisement ({self.PATH}) released by BlueZ.")


# --- Main Execution Logic ---
async def main():
    """
    Main asynchronous function - Sets up D-Bus objects, registers with BlueZ.
    Uses dynamic device name based on MAC address.
    """
    # Determine device name first
    device_name = get_dynamic_device_name(WIFI_INTERFACE, DEFAULT_DEVICE_NAME)

    print(f"Starting Direct D-Bus BLE peripheral '{device_name}'...")
    bus = None
    adapter_path = None
    gatt_manager = None
    ad_manager = None
    app = None # The Application object managing GATT objects
    advertisement = None # The Advertisement object
    # Keep track of exported D-Bus objects for cleanup {path: instance}
    exported_objects = {}

    try:
        print("Connecting to system bus...")
        bus = await dbus_next.aio.MessageBus(bus_type=BusType.SYSTEM).connect()
        print("Connected to system bus.")

        # --- Find Bluetooth Adapter ---
        print("Finding Bluetooth adapter...")
        introspection = await bus.introspect(BLUEZ_SERVICE, '/')
        obj_manager_proxy = bus.get_proxy_object(BLUEZ_SERVICE, '/', introspection)
        obj_manager_iface = obj_manager_proxy.get_interface(DBUS_OM_IFACE)
        managed_objects = await obj_manager_iface.call_get_managed_objects()
        for path, interfaces in managed_objects.items():
            if GATT_MANAGER_IFACE in interfaces:
                adapter_path = path
                print(f"Found GATT Manager at: {adapter_path}")
                # Check for Advertising Manager support
                if LE_ADVERTISING_MANAGER_IFACE not in interfaces:
                    print(f"Warning: Adapter {adapter_path} does not support LE Advertising.")
                    ad_manager = None
                break # Use first found adapter
        if not adapter_path:
            raise Exception("Bluetooth adapter with GATT Manager support not found.")

        # --- Get GATT Manager and Advertising Manager Proxies ---
        adapter_introspection = await bus.introspect(BLUEZ_SERVICE, adapter_path)
        adapter_object = bus.get_proxy_object(BLUEZ_SERVICE, adapter_path, adapter_introspection)
        gatt_manager = adapter_object.get_interface(GATT_MANAGER_IFACE)
        # Get Ad Manager only if supported
        if LE_ADVERTISING_MANAGER_IFACE in adapter_introspection.interfaces:
            ad_manager = adapter_object.get_interface(LE_ADVERTISING_MANAGER_IFACE)
            print("Got GATT Manager and Advertising Manager interfaces.")
        else:
            ad_manager = None # Explicitly set to None if not found
            print("Got GATT Manager interface. Advertising Manager not available.")


        # --- Create Application and GATT Objects ---
        print("Creating GATT objects...")
        # 1. Create the Application object (Object Manager)
        app = Application(bus, APP_PATH)

        # 2. Create the Service
        service = BleService(SERVICE_PATH, SERVICE_UUID, True)

        # 3. Create Characteristics (pass their specific paths)
        char_rw = ReadWriteCharacteristicImpl(CHAR_RW_PATH, service.PATH)
        char_scan = WifiScanCharacteristicImpl(CHAR_SCAN_PATH, service.PATH)
        char_ssid = SetSsidCharacteristicImpl(CHAR_SSID_PATH, service) # Needs service instance
        char_psk = SetPskCharacteristicImpl(CHAR_PSK_PATH, service)   # Needs service instance

        # 4. Create Descriptors (pass their specific paths)
        desc_rw = UserDescriptionDescriptorImpl(DESC_RW_PATH, "Read/Write Value", char_rw.PATH)
        desc_scan = UserDescriptionDescriptorImpl(DESC_SCAN_PATH, "WiFi Scan Trigger/Result", char_scan.PATH)
        desc_ssid = UserDescriptionDescriptorImpl(DESC_SSID_PATH, "Set Target SSID", char_ssid.PATH)
        desc_psk = UserDescriptionDescriptorImpl(DESC_PSK_PATH, "Set Target PSK", char_psk.PATH)

        # --- Link objects together ---
        # Link characteristics to service
        service.add_characteristic_path(char_rw.PATH)
        service.add_characteristic_path(char_scan.PATH)
        service.add_characteristic_path(char_ssid.PATH)
        service.add_characteristic_path(char_psk.PATH)
        # Link descriptors to characteristics
        char_rw.add_descriptor_path(desc_rw.PATH)
        char_scan.add_descriptor_path(desc_scan.PATH)
        char_ssid.add_descriptor_path(desc_ssid.PATH)
        char_psk.add_descriptor_path(desc_psk.PATH)

        # --- Add GATT objects to the Application manager ---
        print("Adding GATT objects to Application manager...")
        app.add_gatt_object(service.PATH, service)
        app.add_gatt_object(char_rw.PATH, char_rw)
        app.add_gatt_object(char_scan.PATH, char_scan)
        app.add_gatt_object(char_ssid.PATH, char_ssid)
        app.add_gatt_object(char_psk.PATH, char_psk)
        app.add_gatt_object(desc_rw.PATH, desc_rw)
        app.add_gatt_object(desc_scan.PATH, desc_scan)
        app.add_gatt_object(desc_ssid.PATH, desc_ssid)
        app.add_gatt_object(desc_psk.PATH, desc_psk)

        # --- Export objects onto D-Bus ---
        print("Exporting objects...")
        # Export the Application object manager itself first
        bus.export(APP_PATH, app); exported_objects[APP_PATH] = app
        # Export all the GATT objects that the Application manages
        for path, instance in app.managed_gatt_objects.items():
            bus.export(path, instance); exported_objects[path] = instance
        print(f"Exported {len(exported_objects)} D-Bus objects (including Application).")

        # --- Register GATT Application ---
        print(f"Registering GATT application with BlueZ using object manager at {APP_PATH}...")
        # Options can be empty: {}
        register_app_options = {}
        await gatt_manager.call_register_application(APP_PATH, register_app_options)
        print("GATT application registered successfully.")

        # --- Create and Register Advertisement (if manager available) ---
        if ad_manager:
            print("Creating and registering advertisement...")
            advertisement = BleAdvertisement(
                ADVERTISEMENT_PATH, # Use specific Ad path
                "peripheral",
                device_name, # Use dynamic name
                [SERVICE_UUID],
                0x0340 # Appearance: Generic Computer
            )
            bus.export(advertisement.PATH, advertisement); exported_objects[advertisement.PATH] = advertisement
            # Ad registration options can be empty: {}
            register_ad_options = {}
            await ad_manager.call_register_advertisement(advertisement.PATH, register_ad_options)
            print("Advertisement registered successfully.")
        else:
            print("Skipping advertisement registration (LEAdvertisingManager not found).")

        print(f"'{device_name}' peripheral setup complete. Running event loop (Press Ctrl+C to stop)...")
        stop_event = asyncio.Event()
        await stop_event.wait() # Keep running until interrupted

    except asyncio.CancelledError:
        print("\nMain task cancelled.")
    except DBusError as e:
         print(f"\nD-Bus Error occurred: {e.type} - {e.text}")
         traceback.print_exc()
    except Exception as e:
        print(f"\nAn error occurred during setup or runtime: {e}")
        print("Traceback:")
        traceback.print_exc()

    finally:
        # --- Cleanup Logic ---
        print("\nShutting down...")
        if bus and bus.connected:
            # 1. Unregister Advertisement
            if ad_manager and advertisement and advertisement.PATH in exported_objects:
                try:
                    print(f"Unregistering advertisement: {advertisement.PATH}")
                    await ad_manager.call_unregister_advertisement(advertisement.PATH)
                except DBusError as e:
                     # Ignore errors if object is already gone
                     if e.type not in ('org.freedesktop.DBus.Error.UnknownObject', 'org.bluez.Error.DoesNotExist'):
                         print(f" D-Bus Error unregistering advertisement: {e.type} - {e.text}")
                except Exception as e: print(f" Error unregistering advertisement: {e}")

            # 2. Unregister GATT Application
            if gatt_manager and app: # Check if app object exists
                try:
                    print(f"Unregistering GATT application: {APP_PATH}")
                    await gatt_manager.call_unregister_application(APP_PATH)
                except DBusError as e:
                     if e.type not in ('org.freedesktop.DBus.Error.UnknownObject', 'org.bluez.Error.DoesNotExist'):
                         print(f" D-Bus Error unregistering application: {e.type} - {e.text}")
                except Exception as e: print(f" Error unregistering application: {e}")

            # 3. Unexport D-Bus objects
            print(f"Unexporting {len(exported_objects)} D-Bus objects...")
            # Iterate over a copy of keys as we modify the dict
            for path in reversed(list(exported_objects.keys())):
                try:
                    bus.unexport(path)
                    # Optional: remove from dict after successful unexport
                    # del exported_objects[path]
                except Exception as e: print(f" Error unexporting path {path}: {e}")
            print("D-Bus objects unexported.")

            # 4. Disconnect bus
            print("Disconnecting from system bus...")
            bus.disconnect()
            print("Disconnected from system bus.")
        else:
            print("Bus connection was not established or already closed.")
        print("Shutdown complete.")


# Run the main asynchronous function
if __name__ == "__main__":
    # Basic check for root privileges
    if os.geteuid() != 0:
        print("Warning: This script typically needs root privileges (sudo).")

    loop = asyncio.get_event_loop()
    main_task = None
    try:
        main_task = asyncio.ensure_future(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received, stopping.")
    finally:
        if main_task and not main_task.done():
            main_task.cancel()
            try:
                loop.run_until_complete(main_task)
            except asyncio.CancelledError:
                pass # Expected on cancellation
        if loop.is_running():
            loop.stop()
        # Shutdown async generators before closing loop
        if not loop.is_closed():
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception as e:
                 print(f"Error during asyncgen shutdown: {e}")
            finally:
                loop.close()
        print("Event loop closed.")

