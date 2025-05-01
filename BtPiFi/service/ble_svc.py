#!/usr/bin/env python3

import asyncio
import dbus_next.aio
from dbus_next import BusType, Variant, DBusError
# Import ServiceInterface, method, dbus_property, PropertyAccess
from dbus_next.service import ServiceInterface, method, dbus_property, PropertyAccess
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor # Included based on user's working version (080b505)
import traceback
import time # Import the time module for sleep
# sys and os imports removed as per user's working version

# --- Configuration ---
APP_PATH = "/com/automationwise/btpifi"
SERVICE_PATH = APP_PATH + "/service0"
# Characteristic Paths
CHAR_RW_PATH = SERVICE_PATH + "/char0"    # Read/Write Char
CHAR_SCAN_PATH = SERVICE_PATH + "/char1"  # WiFi Scan Char
CHAR_SSID_PATH = SERVICE_PATH + "/char2"  # Set SSID Char (NEW)
CHAR_PSK_PATH = SERVICE_PATH + "/char3"   # Set PSK Char (NEW)
# Descriptor Paths
DESC_RW_PATH = CHAR_RW_PATH + "/desc0"
DESC_SCAN_PATH = CHAR_SCAN_PATH + "/desc0"
DESC_SSID_PATH = CHAR_SSID_PATH + "/desc0" # (NEW)
DESC_PSK_PATH = CHAR_PSK_PATH + "/desc0"   # (NEW)
# Advertisement Path (Using path from user's working version)
ADVERTISEMENT_PATH = "/com/automationwise/btpifi/advertisement0"

# Service UUID
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
# Characteristic UUIDs
CHAR_READ_WRITE_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"
WIFI_SCAN_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"
WIFI_SET_SSID_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"
WIFI_SET_PSK_UUID = "133934e4-01f5-4054-a88f-0136e064c49e"
# Descriptor UUID
USER_DESC_UUID = "2901" # Characteristic User Description

# --- Dynamic Naming Configuration --- ADDED BACK ---
# Default Device Name (Used if MAC cannot be read)
DEFAULT_DEVICE_NAME = "BtPiFi-Setup"
# WiFi Interface Name (Adjust if different, e.g., 'wlan1')
WIFI_INTERFACE = "wlan0"
# Static DEVICE_NAME constant removed, will use dynamic name variable

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

# --- Dynamic Naming Function --- ADDED BACK ---
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

# (run_wifi_scan function as provided by user)
def run_wifi_scan():
    ssids = []
    try:
        rescan_cmd = ["sudo", "nmcli", "dev", "wifi", "rescan"]
        print(f"Running command: {' '.join(rescan_cmd)}")
        subprocess.run(rescan_cmd, check=True, timeout=10, capture_output=True)
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
    except FileNotFoundError: return {"error": "nmcli not found"}
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr.strip() if e.stderr else "No stderr output"
        print(f"Error running nmcli: {e}\nStderr: {stderr_output}")
        if "wifi is disabled" in stderr_output.lower(): return {"error": "WiFi is disabled"}
        if "NetworkManager is not running" in stderr_output: return {"error": "NetworkManager is not running"}
        return {"error": f"nmcli failed: {stderr_output[:100]}"}
    except subprocess.TimeoutExpired as e:
        cmd_name = 'rescan' if e.cmd == rescan_cmd else 'list'
        print(f"Error: nmcli {cmd_name} command timed out.")
        return {"error": f"WiFi {cmd_name} timed out"}
    except Exception as e:
        print(f"An unexpected error occurred during WiFi scan: {e}")
        return {"error": f"Unexpected scan error: {str(e)}"}
    print(f"Found SSIDs: {ssids}")
    return {"ssids": ssids}

# --- D-Bus Object Implementations ---
# Structure based on user's working code (080b505)

class Application(ServiceInterface):
    """ Object Manager implementation """
    def __init__(self, bus, path_prefix):
        super().__init__(DBUS_OM_IFACE)
        self.bus = bus
        self.path_prefix = path_prefix
        self.service_objects = {}
    def add_object(self, path, instance): self.service_objects[path] = instance
    def remove_object(self, path):
        if path in self.service_objects: del self.service_objects[path]
    def _get_object_properties(self, instance):
        props = {}
        if isinstance(instance, BleService):
            props['UUID'] = Variant('s', instance.uuid)
            props['Primary'] = Variant('b', instance.primary)
            props['Characteristics'] = Variant('ao', instance.characteristic_paths)
        elif isinstance(instance, BleCharacteristic):
            props['UUID'] = Variant('s', instance.uuid)
            props['Flags'] = Variant('as', instance.flags)
            props['Service'] = Variant('o', instance.service_path)
            props['Descriptors'] = Variant('ao', instance.descriptor_paths)
        elif isinstance(instance, BleDescriptor):
            props['UUID'] = Variant('s', instance.uuid)
            props['Flags'] = Variant('as', instance.flags)
            props['Characteristic'] = Variant('o', instance.characteristic_path)
        return props
    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        print("GetManagedObjects called")
        managed_objects_dict = {}
        for path, instance in self.service_objects.items():
            gatt_props = self._get_object_properties(instance)
            # Using instance.name (interface name) as key, as per user's working version
            if gatt_props and hasattr(instance, 'name'):
                managed_objects_dict[path] = { instance.name: gatt_props }
            else:
                print(f"Warning: Could not get properties or name for object at {path}")
                managed_objects_dict[path] = {}
        return managed_objects_dict

class BleService(ServiceInterface):
    """ Represents the GATT Service """
    PATH = SERVICE_PATH # Class variable path
    def __init__(self, uuid: str, primary: bool):
        super().__init__(GATT_SERVICE_IFACE)
        self.uuid = uuid
        self.primary = primary
        self.characteristic_paths = []
        self._target_ssid = None
        self._target_psk = None

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's': return self.uuid
    @dbus_property(access=PropertyAccess.READ)
    def Primary(self) -> 'b': return self.primary
    @dbus_property(access=PropertyAccess.READ)
    def Characteristics(self) -> 'ao': return self.characteristic_paths
    def add_characteristic_path(self, path: str):
        if path not in self.characteristic_paths: self.characteristic_paths.append(path)

class BleCharacteristic(ServiceInterface):
    """ Base class for GATT Characteristics """
    # PATH defined in subclasses
    def __init__(self, interface_name, uuid: str, flags: list[str], service_path: str):
        super().__init__(interface_name)
        self.uuid = uuid
        self.flags = flags
        self.service_path = service_path
        self.descriptor_paths = []
        self._value = bytearray()
        # _notifying removed as per user's working version base

    @dbus_property(access=PropertyAccess.READ)
    def UUID(self) -> 's': return self.uuid
    @dbus_property(access=PropertyAccess.READ)
    def Flags(self) -> 'as': return self.flags
    @dbus_property(access=PropertyAccess.READ)
    def Service(self) -> 'o': return self.service_path
    @dbus_property(access=PropertyAccess.READ)
    def Descriptors(self) -> 'ao': return self.descriptor_paths
    def add_descriptor_path(self, path: str):
        if path not in self.descriptor_paths: self.descriptor_paths.append(path)
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f"Default ReadValue called for {self.uuid}. Override in subclass.")
        if 'read' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        # Offset handling removed as per user's working version base
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for {self.uuid}. Override in subclass.")
        if 'write' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        # Offset handling removed as per user's working version base
        self._value = bytearray(value)
        print(f"Wrote {len(value)} bytes.")
    @method()
    async def StartNotify(self): raise DBusError('org.bluez.Error.NotSupported', 'Notify not supported')
    @method()
    async def StopNotify(self): pass

class BleDescriptor(ServiceInterface):
    """ Base class for GATT Descriptors """
    # PATH defined in subclasses
    def __init__(self, interface_name, uuid: str, flags: list[str], characteristic_path: str):
        super().__init__(interface_name)
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
        print(f"Default ReadValue called for Descriptor {self.uuid}. Override if needed.")
        if 'read' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        # Offset handling removed as per user's working version base
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for Descriptor {self.uuid}. Override if needed.")
        if 'write' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        # Offset handling removed as per user's working version base
        self._value = bytearray(value)
        print(f"Wrote {len(value)} bytes to descriptor.")

# --- Application Specific Characteristic Implementations ---
# Structure based on user's working code (080b505)

class ReadWriteCharacteristicImpl(BleCharacteristic):
    """ Simple Read/Write characteristic """
    PATH = CHAR_RW_PATH # Class variable path
    def __init__(self, service_path: str):
        super().__init__(GATT_CHRC_IFACE, CHAR_READ_WRITE_UUID, ["read", "write"], service_path)
        self._value = bytearray("Initial Value", "utf-8")
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(">>> ReadWriteCharacteristicImpl.ReadValue called")
        print(f"Client READ request received (RW Char). Sending value: {self._value.decode('utf-8', errors='replace')}")
        return bytes(self._value) # Return directly
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> ReadWriteCharacteristicImpl.WriteValue called")
        try:
            received_string = bytes(value).decode("utf-8")
            print(f"Client WRITE request received (RW Char). New value: {received_string}")
            self._value = bytearray(value) # Update directly
        except UnicodeDecodeError:
            print("Error (RW Char): Received invalid UTF-8 data.")

class WifiScanCharacteristicImpl(BleCharacteristic):
    """ Read-only characteristic for WiFi scan results """
    PATH = CHAR_SCAN_PATH # Class variable path
    def __init__(self, service_path: str):
        super().__init__(GATT_CHRC_IFACE, WIFI_SCAN_UUID, ["read"], service_path)
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(">>> WifiScanCharacteristicImpl.ReadValue called")
        print("Client READ request received (WiFi Scan Char). Starting scan...")
        loop = asyncio.get_running_loop()
        try:
            scan_result_dict = await loop.run_in_executor(None, run_wifi_scan)
            result_json = json.dumps(scan_result_dict)
            print(f"Sending scan result: {result_json}")
            # No need to store in self._value if ReadValue returns directly
            return bytes(result_json, "utf-8")
        except Exception as e:
            print(f"Error processing scan result in ReadValue: {e}")
            error_result = json.dumps({"error": f"Failed to process scan: {str(e)}"})
            return bytes(error_result, "utf-8")
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')

class SetSsidCharacteristicImpl(BleCharacteristic):
    """ Characteristic to receive the target WiFi SSID """
    PATH = CHAR_SSID_PATH # Class variable path
    def __init__(self, service: BleService): # Takes service instance
        super().__init__(GATT_CHRC_IFACE, WIFI_SET_SSID_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> SetSsidCharacteristicImpl.WriteValue called")
        try:
            ssid = bytes(value).decode("utf-8")
            print(f"Received target SSID: {ssid}")
            self.service._target_ssid = ssid # Store on service
        except UnicodeDecodeError:
            print("Error: Received invalid UTF-8 data for SSID.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for SSID')
        except Exception as e:
            print(f"Error processing SSID write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process SSID: {e}')
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')

class SetPskCharacteristicImpl(BleCharacteristic):
    """ Characteristic to receive the target WiFi PSK (Password) """
    PATH = CHAR_PSK_PATH # Class variable path
    def __init__(self, service: BleService): # Takes service instance
        super().__init__(GATT_CHRC_IFACE, WIFI_SET_PSK_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> SetPskCharacteristicImpl.WriteValue called")
        try:
            psk = bytes(value).decode("utf-8")
            print(f"Received target PSK (length={len(psk)})") # Avoid printing actual PSK
            self.service._target_psk = psk # Store on service
        except UnicodeDecodeError:
            print("Error: Received invalid UTF-8 data for PSK.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for PSK')
        except Exception as e:
            print(f"Error processing PSK write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process PSK: {e}')
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')

# --- Application Specific Descriptors ---
# Structure based on user's working code (080b505)
class UserDescriptionDescriptorImpl(BleDescriptor):
    """ Read-only User Description Descriptor """
    # PATH is set dynamically in __init__
    def __init__(self, description: str, characteristic_path: str):
        super().__init__(GATT_DESC_IFACE, USER_DESC_UUID, ["read"], characteristic_path)
        self._value = bytearray(description, "utf-8")
        self.PATH = characteristic_path + "/desc0" # Set instance path
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> UserDescriptionDescriptorImpl.ReadValue called for {self.characteristic_path}")
        return bytes(self._value) # Return directly
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')

# --- Advertising Implementation ---
# Structure based on user's working code (080b505)
class BleAdvertisement(ServiceInterface):
    """ Represents the BLE Advertisement object """
    PATH = ADVERTISEMENT_PATH # Class variable path from user's working version
    def __init__(self, ad_type: str, local_name: str, service_uuids: 'list[str]', appearance: int):
        super().__init__(LE_ADVERTISEMENT_IFACE)
        self.type = ad_type; self.local_name = local_name; self.service_uuids = service_uuids; self.appearance = appearance
    @dbus_property(access=PropertyAccess.READ)
    def Type(self) -> 's': return self.type
    @dbus_property(access=PropertyAccess.READ)
    def LocalName(self) -> 's': return self.local_name
    @dbus_property(access=PropertyAccess.READ)
    def ServiceUUIDs(self) -> 'as': return self.service_uuids
    @dbus_property(access=PropertyAccess.READ)
    def Appearance(self) -> 'q': return self.appearance
    @method()
    def Release(self): print(f"Advertisement ({self.PATH}) released")


# --- Main Execution Logic ---
# Structure based on user's working code (080b505), with dynamic name added
async def main():
    """
    Main asynchronous function - Based on user's working code structure.
    Includes dynamic device name.
    """
    # --- Determine device name --- ADDED BACK ---
    device_name = get_dynamic_device_name(WIFI_INTERFACE, DEFAULT_DEVICE_NAME)

    print(f"Starting Direct D-Bus BLE peripheral '{device_name}'...") # Use dynamic name
    bus = None
    adapter_path = None
    gatt_manager = None
    ad_manager = None
    app = None
    advertisement = None
    service = None
    # Characteristics and Descriptors defined within try block
    exported_paths = [] # Track exported paths

    try:
        print("Connecting to system bus...")
        bus = await dbus_next.aio.MessageBus(bus_type=BusType.SYSTEM).connect()
        print("Connected to system bus.")

        # --- Find Bluetooth Adapter ---
        print("Finding Bluetooth adapter...")
        introspection = await bus.introspect(BLUEZ_SERVICE, '/')
        obj_manager = bus.get_proxy_object(BLUEZ_SERVICE, '/', introspection)
        interface = obj_manager.get_interface(DBUS_OM_IFACE)
        managed_objects = await interface.call_get_managed_objects()
        for path, interfaces in managed_objects.items():
            if GATT_MANAGER_IFACE in interfaces:
                adapter_path = path
                print(f"Found GATT Manager at: {adapter_path}")
                break
        if not adapter_path: raise Exception("Bluetooth adapter with GATT Manager not found.")

        # --- Get GATT Manager and Advertising Manager ---
        gatt_introspection = await bus.introspect(BLUEZ_SERVICE, adapter_path)
        adapter_object = bus.get_proxy_object(BLUEZ_SERVICE, adapter_path, gatt_introspection)
        gatt_manager = adapter_object.get_interface(GATT_MANAGER_IFACE)
        # Check for Ad Manager support (might fail if adapter doesn't support it)
        try:
            ad_manager = adapter_object.get_interface(LE_ADVERTISING_MANAGER_IFACE)
            print("Got GATT Manager and Advertising Manager interfaces.")
        except Exception:
             ad_manager = None
             print("Got GATT Manager interface. Advertising Manager not available or failed to get.")

        # --- Create Application Objects ---
        print("Creating GATT objects...")
        app = Application(bus, APP_PATH)
        service = BleService(SERVICE_UUID, True)
        # Create characteristics
        char_rw = ReadWriteCharacteristicImpl(service.PATH)
        char_scan = WifiScanCharacteristicImpl(service.PATH)
        char_ssid = SetSsidCharacteristicImpl(service)
        char_psk = SetPskCharacteristicImpl(service)
        # Create descriptors
        desc_rw = UserDescriptionDescriptorImpl("Read/Write Value", char_rw.PATH)
        desc_scan = UserDescriptionDescriptorImpl("WiFi Scan Trigger/Result", char_scan.PATH)
        desc_ssid = UserDescriptionDescriptorImpl("Set Target SSID", char_ssid.PATH)
        desc_psk = UserDescriptionDescriptorImpl("Set Target PSK", char_psk.PATH)

        # --- Link objects together ---
        service.add_characteristic_path(char_rw.PATH)
        service.add_characteristic_path(char_scan.PATH)
        service.add_characteristic_path(char_ssid.PATH)
        service.add_characteristic_path(char_psk.PATH)
        char_rw.add_descriptor_path(desc_rw.PATH)
        char_scan.add_descriptor_path(desc_scan.PATH)
        char_ssid.add_descriptor_path(desc_ssid.PATH)
        char_psk.add_descriptor_path(desc_psk.PATH)

        # --- Add object instances to Application for GetManagedObjects ---
        print("Adding objects to Object Manager...")
        app.add_object(service.PATH, service)
        app.add_object(char_rw.PATH, char_rw)
        app.add_object(char_scan.PATH, char_scan)
        app.add_object(char_ssid.PATH, char_ssid)
        app.add_object(char_psk.PATH, char_psk)
        app.add_object(desc_rw.PATH, desc_rw)
        app.add_object(desc_scan.PATH, desc_scan)
        app.add_object(desc_ssid.PATH, desc_ssid)
        app.add_object(desc_psk.PATH, desc_psk)

        # --- Export objects onto D-Bus ---
        print("Exporting objects...")
        bus.export(APP_PATH, app); exported_paths.append(APP_PATH)
        bus.export(service.PATH, service); exported_paths.append(service.PATH)
        bus.export(char_rw.PATH, char_rw); exported_paths.append(char_rw.PATH)
        bus.export(char_scan.PATH, char_scan); exported_paths.append(char_scan.PATH)
        bus.export(char_ssid.PATH, char_ssid); exported_paths.append(char_ssid.PATH)
        bus.export(char_psk.PATH, char_psk); exported_paths.append(char_psk.PATH)
        bus.export(desc_rw.PATH, desc_rw); exported_paths.append(desc_rw.PATH)
        bus.export(desc_scan.PATH, desc_scan); exported_paths.append(desc_scan.PATH)
        bus.export(desc_ssid.PATH, desc_ssid); exported_paths.append(desc_ssid.PATH)
        bus.export(desc_psk.PATH, desc_psk); exported_paths.append(desc_psk.PATH)
        print("GATT objects exported.")

        # --- Register GATT Application ---
        print("Registering GATT application...")
        await gatt_manager.call_register_application(APP_PATH, {})
        print("GATT application registered successfully.")

        # --- Create and Register Advertisement ---
        if ad_manager: # Only proceed if Ad Manager was found
            print("Creating and registering advertisement...")
            # --- Use dynamic device_name here --- MODIFIED ---
            advertisement = BleAdvertisement("peripheral", device_name, [SERVICE_UUID], 0x0340)
            bus.export(advertisement.PATH, advertisement); exported_paths.append(advertisement.PATH)
            await ad_manager.call_register_advertisement(advertisement.PATH, {})
            print("Advertisement registered successfully.")
        else:
            print("Skipping advertisement registration (LEAdvertisingManager not available).")

        print("Peripheral setup complete. Running event loop (Press Ctrl+C to stop)...")
        stop_event = asyncio.Event()
        await stop_event.wait()

    except asyncio.CancelledError: print("Main task cancelled.")
    except DBusError as e:
        print(f"D-Bus Error occurred: {e.type} - {e.text}")
        traceback.print_exc()
    except Exception as e:
        print(f"An error occurred during setup or runtime: {e}")
        print("Traceback:")
        traceback.print_exc()

    finally:
        # Using shutdown logic from user's working version (080b505)
        print("Shutting down...")
        if bus and bus.connected:
            # Unregister Ad
            if ad_manager and advertisement:
                try:
                    print("Unregistering advertisement...")
                    await ad_manager.call_unregister_advertisement(advertisement.PATH)
                except DBusError as e:
                    if e.type != 'org.freedesktop.DBus.Error.UnknownObject' and e.type != 'org.bluez.Error.DoesNotExist': print(f"D-Bus Error unregistering advertisement: {e.type} - {e.text}")
                except Exception as e: print(f"Error unregistering advertisement: {e}")
            # Unregister App
            if gatt_manager and app:
                try:
                    print("Unregistering GATT application...")
                    await gatt_manager.call_unregister_application(APP_PATH)
                except DBusError as e:
                    if e.type != 'org.freedesktop.DBus.Error.UnknownObject' and e.type != 'org.bluez.Error.DoesNotExist': print(f"D-Bus Error unregistering application: {e.type} - {e.text}")
                except Exception as e: print(f"Error unregistering application: {e}")
            # Unexport paths
            print(f"Unexporting {len(exported_paths)} D-Bus objects...")
            for path in reversed(exported_paths):
                try: bus.unexport(path)
                except Exception as e: print(f"Error unexporting path {path}: {e}")
            print("D-Bus objects unexported.")
            # Disconnect bus
            print("Disconnecting from system bus...")
            bus.disconnect()
            print("Disconnected from system bus.")
        else: print("Bus connection was not established or already closed.")
        print("Shutdown complete.")


# Run the main asynchronous function
# Using main loop execution from user's working version (080b505)
if __name__ == "__main__":
    # Check for root privileges (optional but recommended)
    import os # Added back import needed for check
    if os.geteuid() != 0:
        print("Warning: This script typically needs root privileges (sudo) to access the D-Bus system bus and run 'nmcli'.")

    loop = asyncio.get_event_loop()
    main_task = None
    try:
        main_task = asyncio.ensure_future(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received, stopping.")
    finally:
        if main_task:
            main_task.cancel()
            try: loop.run_until_complete(main_task)
            except asyncio.CancelledError: pass
        if loop.is_running(): loop.stop()
        if not loop.is_closed(): loop.run_until_complete(loop.shutdown_asyncgens()); loop.close()
        print("Event loop closed.")
