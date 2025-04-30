#!/usr/bin/env python3

import asyncio
import dbus_next.aio
from dbus_next import BusType, Variant, DBusError
# Import ServiceInterface, method, dbus_property, PropertyAccess
from dbus_next.service import ServiceInterface, method, dbus_property, PropertyAccess
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
import traceback
import time # Import the time module for sleep

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

# Service UUID
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
# Characteristic UUIDs
CHAR_READ_WRITE_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"
WIFI_SCAN_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"
WIFI_SET_SSID_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"
WIFI_SET_PSK_UUID = "133934e4-01f5-4054-a88f-0136e064c49e"
# Descriptor UUID
USER_DESC_UUID = "2901" # Characteristic User Description

DEVICE_NAME = "BtPiFi"
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


# (run_wifi_scan function remains the same)
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

class Application(ServiceInterface):
    # (Application class remains the same)
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
            if gatt_props: managed_objects_dict[path] = { instance.name: gatt_props }
            else: print(f"Warning: Could not get properties for object at {path}"); managed_objects_dict[path] = {}
        return managed_objects_dict

class BleService(ServiceInterface):
    # (BleService class remains mostly the same)
    PATH = SERVICE_PATH
    def __init__(self, uuid: str, primary: bool):
        super().__init__(GATT_SERVICE_IFACE)
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
        if path not in self.characteristic_paths: self.characteristic_paths.append(path)

class BleCharacteristic(ServiceInterface):
    # (BleCharacteristic base class remains the same)
    def __init__(self, interface_name, uuid: str, flags: 'list[str]', service_path: str):
        super().__init__(interface_name)
        self.uuid = uuid
        self.flags = flags
        self.service_path = service_path
        self.descriptor_paths = []
        self._value = bytearray()
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
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for {self.uuid}. Override in subclass.")
        if 'write' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        self._value = bytearray(value)
        print(f"Wrote {len(value)} bytes.")
    @method()
    async def StartNotify(self): raise DBusError('org.bluez.Error.NotSupported', 'Notify not supported')
    @method()
    async def StopNotify(self): pass

class BleDescriptor(ServiceInterface):
    # (BleDescriptor base class remains the same)
    def __init__(self, interface_name, uuid: str, flags: 'list[str]', characteristic_path: str):
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
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for Descriptor {self.uuid}. Override if needed.")
        if 'write' not in self.flags: raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        self._value = bytearray(value)
        print(f"Wrote {len(value)} bytes to descriptor.")

# --- Application Specific Characteristic Implementations ---

class ReadWriteCharacteristicImpl(BleCharacteristic):
    # (ReadWriteCharacteristicImpl remains the same)
    PATH = CHAR_RW_PATH
    def __init__(self, service_path: str):
        super().__init__(GATT_CHRC_IFACE, CHAR_READ_WRITE_UUID, ["read", "write"], service_path)
        self._value = bytearray("Initial Value", "utf-8")
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(">>> ReadWriteCharacteristicImpl.ReadValue called")
        print(f"Client READ request received (RW Char). Sending value: {self._value.decode('utf-8', errors='replace')}")
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> ReadWriteCharacteristicImpl.WriteValue called")
        try:
            received_string = bytes(value).decode("utf-8")
            print(f"Client WRITE request received (RW Char). New value: {received_string}")
            self._value = bytearray(value)
        except UnicodeDecodeError:
            print("Error (RW Char): Received invalid UTF-8 data.")

class WifiScanCharacteristicImpl(BleCharacteristic):
    # (WifiScanCharacteristicImpl remains the same)
    PATH = CHAR_SCAN_PATH
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
            return bytes(result_json, "utf-8")
        except Exception as e:
            print(f"Error processing scan result in ReadValue: {e}")
            error_result = json.dumps({"error": f"Failed to process scan: {str(e)}"})
            return bytes(error_result, "utf-8")
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')

# *** NEW Writeable Characteristic Classes ***

class SetSsidCharacteristicImpl(BleCharacteristic):
    """Characteristic to receive the target WiFi SSID."""
    PATH = CHAR_SSID_PATH
    def __init__(self, service: BleService): # Takes service instance
        super().__init__(GATT_CHRC_IFACE, WIFI_SET_SSID_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> SetSsidCharacteristicImpl.WriteValue called")
        try:
            # Decode SSID as UTF-8
            ssid = bytes(value).decode("utf-8")
            print(f"Received target SSID: {ssid}")
            # Store it on the service object
            self.service._target_ssid = ssid
        except UnicodeDecodeError:
            print("Error: Received invalid UTF-8 data for SSID.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for SSID')
        except Exception as e:
            print(f"Error processing SSID write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process SSID: {e}')

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        # Writes only, reads not permitted
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')


class SetPskCharacteristicImpl(BleCharacteristic):
    """Characteristic to receive the target WiFi PSK (Password)."""
    # SECURITY WARNING: Sending PSK over unencrypted BLE is insecure!
    PATH = CHAR_PSK_PATH
    def __init__(self, service: BleService): # Takes service instance
        super().__init__(GATT_CHRC_IFACE, WIFI_SET_PSK_UUID, ["write"], service.PATH)
        self.service = service # Store reference to service

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> SetPskCharacteristicImpl.WriteValue called")
        try:
            # Decode PSK as UTF-8 (WPA PSKs are typically printable strings)
            psk = bytes(value).decode("utf-8")
            print(f"Received target PSK (length={len(psk)})") # Avoid printing actual PSK
            # Store it on the service object
            self.service._target_psk = psk
        except UnicodeDecodeError:
            print("Error: Received invalid UTF-8 data for PSK.")
            raise DBusError('org.bluez.Error.InvalidValueLength', 'Invalid UTF-8 for PSK')
        except Exception as e:
            print(f"Error processing PSK write: {e}")
            raise DBusError('org.bluez.Error.Failed', f'Failed to process PSK: {e}')

    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        # Writes only, reads not permitted
         raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')

# --- Application Specific Descriptors ---
class UserDescriptionDescriptorImpl(BleDescriptor):
    # (UserDescriptionDescriptorImpl remains the same)
    def __init__(self, description: str, characteristic_path: str):
        super().__init__(GATT_DESC_IFACE, USER_DESC_UUID, ["read"], characteristic_path)
        self._value = bytearray(description, "utf-8")
        self.PATH = characteristic_path + "/desc0"
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> UserDescriptionDescriptorImpl.ReadValue called for {self.characteristic_path}")
        return bytes(self._value)
    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')

# --- Advertising Implementation ---
class BleAdvertisement(ServiceInterface):
    # (BleAdvertisement class remains the same)
    PATH = "/com/example/advertisement0"
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
async def main():
    """
    Main asynchronous function - Added writeable characteristics.
    """
    #device_name = get_dynamic_device_name(WIFI_INTERFACE, DEFAULT_DEVICE_NAME)

    print(f"Starting Direct D-Bus BLE peripheral '{DEVICE_NAME}'...")
    bus = None
    adapter_path = None
    gatt_manager = None
    ad_manager = None
    app = None
    advertisement = None
    service = None
    char_rw = None
    char_scan = None
    char_ssid = None # New char objects
    char_psk = None
    desc_rw = None
    desc_scan = None
    desc_ssid = None # New desc objects
    desc_psk = None
    exported_paths = []

    try:
        print("Connecting to system bus...")
        bus = await dbus_next.aio.MessageBus(bus_type=BusType.SYSTEM).connect()
        print("Connected to system bus.")

        # --- Find Bluetooth Adapter ---
        print("Finding Bluetooth adapter...")
        # (Adapter finding logic remains the same)
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
        ad_manager = adapter_object.get_interface(LE_ADVERTISING_MANAGER_IFACE)
        print("Got GATT Manager and Advertising Manager interfaces.")

        # --- Create Application Objects ---
        print("Creating GATT objects...")
        app = Application(bus, APP_PATH)
        service = BleService(SERVICE_UUID, True)
        # Create existing chars
        char_rw = ReadWriteCharacteristicImpl(service.PATH)
        char_scan = WifiScanCharacteristicImpl(service.PATH)
        desc_rw = UserDescriptionDescriptorImpl("Read/Write Value", char_rw.PATH)
        desc_scan = UserDescriptionDescriptorImpl("WiFi Scan Trigger/Result", char_scan.PATH)
        # Create NEW writeable chars & descriptors
        char_ssid = SetSsidCharacteristicImpl(service) # Pass service instance
        char_psk = SetPskCharacteristicImpl(service)   # Pass service instance
        desc_ssid = UserDescriptionDescriptorImpl("Set Target SSID", char_ssid.PATH)
        desc_psk = UserDescriptionDescriptorImpl("Set Target PSK", char_psk.PATH)

        # Link characteristics to service
        service.add_characteristic_path(char_rw.PATH)
        service.add_characteristic_path(char_scan.PATH)
        service.add_characteristic_path(char_ssid.PATH) # Add new chars
        service.add_characteristic_path(char_psk.PATH)
        # Link descriptors to characteristics
        char_rw.add_descriptor_path(desc_rw.PATH)
        char_scan.add_descriptor_path(desc_scan.PATH)
        char_ssid.add_descriptor_path(desc_ssid.PATH) # Add new descs
        char_psk.add_descriptor_path(desc_psk.PATH)

        # --- Add object instances to Application for GetManagedObjects ---
        print("Adding objects to Object Manager...")
        app.add_object(service.PATH, service)
        app.add_object(char_rw.PATH, char_rw)
        app.add_object(char_scan.PATH, char_scan)
        app.add_object(char_ssid.PATH, char_ssid) # Add new chars
        app.add_object(char_psk.PATH, char_psk)
        app.add_object(desc_rw.PATH, desc_rw)
        app.add_object(desc_scan.PATH, desc_scan)
        app.add_object(desc_ssid.PATH, desc_ssid) # Add new descs
        app.add_object(desc_psk.PATH, desc_psk)

        # --- Export objects onto D-Bus ---
        print("Exporting objects...")
        bus.export(APP_PATH, app); exported_paths.append(APP_PATH)
        bus.export(service.PATH, service); exported_paths.append(service.PATH)
        bus.export(char_rw.PATH, char_rw); exported_paths.append(char_rw.PATH)
        bus.export(char_scan.PATH, char_scan); exported_paths.append(char_scan.PATH)
        bus.export(char_ssid.PATH, char_ssid); exported_paths.append(char_ssid.PATH) # Export new chars
        bus.export(char_psk.PATH, char_psk); exported_paths.append(char_psk.PATH)
        bus.export(desc_rw.PATH, desc_rw); exported_paths.append(desc_rw.PATH)
        bus.export(desc_scan.PATH, desc_scan); exported_paths.append(desc_scan.PATH)
        bus.export(desc_ssid.PATH, desc_ssid); exported_paths.append(desc_ssid.PATH) # Export new descs
        bus.export(desc_psk.PATH, desc_psk); exported_paths.append(desc_psk.PATH)
        print("GATT objects exported.")

        # --- Register GATT Application ---
        print("Registering GATT application...")
        await gatt_manager.call_register_application(APP_PATH, {})
        print("GATT application registered successfully.")

        # --- Create and Register Advertisement ---
        print("Creating and registering advertisement...")
        advertisement = BleAdvertisement("peripheral", DEVICE_NAME, [SERVICE_UUID], 0x0340)
        bus.export(advertisement.PATH, advertisement); exported_paths.append(advertisement.PATH)
        await ad_manager.call_register_advertisement(advertisement.PATH, {})
        print("Advertisement registered successfully.")

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
        # ... (shutdown logic remains the same, unexports all paths in exported_paths) ...
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
if __name__ == "__main__":
    # ... (main loop execution remains the same) ...
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

