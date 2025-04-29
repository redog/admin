#!/usr/bin/env python3

import asyncio
import dbus_next.aio
from dbus_next import BusType, Variant, DBusError
from dbus_next.service import ServiceInterface, method, dbus_property
from dbus_next.constants import PropertyAccess
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
import traceback

# --- Configuration ---
APP_PATH = "/com/example" # Base path for our objects on D-Bus
SERVICE_PATH = APP_PATH + "/service0"
CHAR_RW_PATH = SERVICE_PATH + "/char0" # Read/Write Char
CHAR_SCAN_PATH = SERVICE_PATH + "/char1" # WiFi Scan Char
DESC_RW_PATH = CHAR_RW_PATH + "/desc0"   # Descriptor for Read/Write Char
DESC_SCAN_PATH = CHAR_SCAN_PATH + "/desc0" # Descriptor for WiFi Scan Char

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHAR_READ_WRITE_UUID = "12345678-1234-5678-1234-56789abcdef1"
WIFI_SCAN_UUID = "12345678-1234-5678-1234-56789abcdef2"
# Standard UUID for Characteristic User Description Descriptor
USER_DESC_UUID = "2901"

DEVICE_NAME = "MyRPiDirectDBus"
BLUEZ_SERVICE = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE =      'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE =    'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE =    'org.bluez.GattCharacteristic1'
GATT_DESC_IFACE =    'org.bluez.GattDescriptor1' # Added Descriptor Interface
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'


# --- Helper Function for WiFi Scan (same as before) ---
def run_wifi_scan():
    """
    Runs nmcli to scan for WiFi networks and returns a list of SSIDs.
    This is a blocking function intended to be run in an executor.
    """
    ssids = []
    try:
        cmd = ["nmcli", "-t", "-f", "SSID", "dev", "wifi", "list", "--rescan", "yes"]
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=15)
        output = result.stdout.strip()
        print(f"Scan output:\n{output}")
        if output:
            found_ssids = set(filter(None, output.split('\n')))
            ssids = sorted(list(found_ssids))
    except FileNotFoundError:
        print("Error: 'nmcli' command not found.")
        return {"error": "nmcli not found"}
    except subprocess.CalledProcessError as e:
        print(f"Error running nmcli: {e}")
        print(f"Stderr: {e.stderr}")
        if "wifi is disabled" in e.stderr.lower():
             return {"error": "WiFi is disabled"}
        return {"error": f"nmcli failed: {e.stderr[:100]}"}
    except subprocess.TimeoutExpired:
        print("Error: nmcli command timed out.")
        return {"error": "WiFi scan timed out"}
    except Exception as e:
        print(f"An unexpected error occurred during WiFi scan: {e}")
        return {"error": f"Unexpected scan error: {str(e)}"}

    print(f"Found SSIDs: {ssids}")
    return {"ssids": ssids}

# --- D-Bus Service/Characteristic/Descriptor Implementations ---

class Application(ServiceInterface):
    """
    org.freedesktop.DBus.ObjectManager interface implementation.
    """
    def __init__(self, bus, path_prefix):
        super().__init__(DBUS_OM_IFACE)
        self.bus = bus
        self.path_prefix = path_prefix
        self.managed_objects = {}

    def add_object(self, path, interfaces_and_properties):
        self.managed_objects[path] = interfaces_and_properties

    def remove_object(self, path):
        if path in self.managed_objects:
            del self.managed_objects[path]

    def update_object_properties(self, path, interface, properties):
        if path in self.managed_objects and interface in self.managed_objects[path]:
            self.managed_objects[path][interface].update(properties)
        elif path in self.managed_objects:
             self.managed_objects[path][interface] = properties

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        print("GetManagedObjects called")
        return self.managed_objects


class BaseGattInterface(ServiceInterface):
    """Base class for GATT Service, Characteristic, and Descriptor interfaces."""
    def __init__(self, interface_name):
        super().__init__(interface_name)
        self._properties_dict = {}

    def _add_property(self, name: str, value, signature: str, emit_signal=False):
        self._properties_dict[name] = {'value': value, 'signature': signature}

    def _update_property(self, name: str, value):
        if name in self._properties_dict:
            self._properties_dict[name]['value'] = value
        else:
            raise KeyError(f"Property {name} not defined")

    def _get_property_variant(self, name: str) -> Variant:
         if name in self._properties_dict:
             prop = self._properties_dict[name]
             return Variant(prop['signature'], prop['value'])
         else:
             raise KeyError(f"Property {name} not defined")

    # --- org.freedesktop.DBus.Properties Methods ---
    @method()
    async def Get(self, interface_name: 's', property_name: 's') -> 'v':
        if interface_name != self.name:
            raise DBusError('org.freedesktop.DBus.Error.InvalidArgs', f'No such interface "{interface_name}"')
        try:
            print(f"Get property: {interface_name}.{property_name}")
            return self._get_property_variant(property_name)
        except KeyError:
             raise DBusError('org.freedesktop.DBus.Error.InvalidArgs', f'No such property "{property_name}"')

    @method()
    async def GetAll(self, interface_name: 's') -> 'a{sv}':
        if interface_name != self.name:
            raise DBusError('org.freedesktop.DBus.Error.InvalidArgs', f'No such interface "{interface_name}"')
        print(f"GetAll properties for: {interface_name}")
        return {name: self._get_property_variant(name) for name in self._properties_dict}

    @method()
    async def Set(self, interface_name: 's', property_name: 's', value: 'v'):
        raise DBusError('org.freedesktop.DBus.Error.PropertyReadOnly', f'Property "{property_name}" is read-only')

    def get_properties_for_om(self):
        """Returns properties in the {prop_name: variant} format needed for GetManagedObjects."""
        return {name: self._get_property_variant(name) for name in self._properties_dict}


class BleService(BaseGattInterface):
    """
    org.bluez.GattService1 interface implementation.
    """
    PATH = SERVICE_PATH

    def __init__(self, uuid: str, primary: bool):
        super().__init__(GATT_SERVICE_IFACE)
        self._add_property("UUID", uuid, 's')
        self._add_property("Primary", primary, 'b')
        self._add_property("Characteristics", [], 'ao')

    def add_characteristic_path(self, path: str):
        char_paths = self._properties_dict["Characteristics"]['value']
        if path not in char_paths:
            char_paths.append(path)
            self._update_property("Characteristics", char_paths)

    def get_interfaces_and_properties(self):
        """Returns interfaces and properties for Object Manager."""
        return { GATT_SERVICE_IFACE: self.get_properties_for_om() }


class BleCharacteristic(BaseGattInterface):
    """
    org.bluez.GattCharacteristic1 interface implementation.
    """
    # PATH needs to be defined in subclasses

    def __init__(self, uuid: str, flags: 'list[str]', service_path: str):
        super().__init__(GATT_CHRC_IFACE)
        self._add_property("UUID", uuid, 's')
        self._add_property("Flags", flags, 'as')
        self._add_property("Service", service_path, 'o')
        self._value = bytearray()
        # Add Descriptors property (array of object paths)
        self._add_property("Descriptors", [], 'ao')

    def add_descriptor_path(self, path: str):
        """Adds a descriptor's object path to the list."""
        desc_paths = self._properties_dict["Descriptors"]['value']
        if path not in desc_paths:
            desc_paths.append(path)
            self._update_property("Descriptors", desc_paths)

    # --- org.bluez.GattCharacteristic1 Methods ---
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f"Default ReadValue called for {self._properties_dict['UUID']['value']}. Override in subclass.")
        if 'read' not in self._properties_dict['Flags']['value']:
             raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        return self._value

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(f"Default WriteValue called for {self._properties_dict['UUID']['value']}. Override in subclass.")
        if 'write' not in self._properties_dict['Flags']['value']:
             raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        self._value = value
        print(f"Wrote {len(value)} bytes.")

    @method()
    async def StartNotify(self):
        raise DBusError('org.bluez.Error.NotSupported', 'Notify not supported')

    @method()
    async def StopNotify(self):
        pass

    def get_interfaces_and_properties(self):
        """Returns interfaces and properties for Object Manager."""
        return { GATT_CHRC_IFACE: self.get_properties_for_om() }


# *** NEW Descriptor Class ***
class BleDescriptor(BaseGattInterface):
    """
    org.bluez.GattDescriptor1 interface implementation.
    """
    # PATH needs to be defined in subclasses

    def __init__(self, uuid: str, flags: 'list[str]', characteristic_path: str):
        super().__init__(GATT_DESC_IFACE)
        self._add_property("UUID", uuid, 's')
        self._add_property("Flags", flags, 'as') # Array of strings
        self._add_property("Characteristic", characteristic_path, 'o') # Object path
        self._value = bytearray() # Internal storage for descriptor value

    # --- org.bluez.GattDescriptor1 Methods ---
    @method()
    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        """Handles read requests."""
        print(f"Default ReadValue called for Descriptor {self._properties_dict['UUID']['value']}. Override if needed.")
        if 'read' not in self._properties_dict['Flags']['value']:
             raise DBusError('org.bluez.Error.NotPermitted', 'Read not permitted')
        return self._value

    @method()
    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        """Handles write requests."""
        print(f"Default WriteValue called for Descriptor {self._properties_dict['UUID']['value']}. Override if needed.")
        if 'write' not in self._properties_dict['Flags']['value']:
             raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')
        self._value = value
        print(f"Wrote {len(value)} bytes to descriptor.")

    def get_interfaces_and_properties(self):
        """Returns interfaces and properties for Object Manager."""
        return { GATT_DESC_IFACE: self.get_properties_for_om() }


# --- Application Specific Characteristics ---

class ReadWriteCharacteristic(BleCharacteristic):
    """Custom implementation for the read/write characteristic."""
    PATH = CHAR_RW_PATH

    def __init__(self, service_path: str):
        super().__init__(CHAR_READ_WRITE_UUID, ["read", "write"], service_path)
        self._value = bytearray("Initial Value", "utf-8")

    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(">>> ReadWriteCharacteristic.ReadValue called")
        print(f"Client READ request received (RW Char). Sending value: {self._value.decode('utf-8', errors='replace')}")
        return self._value

    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        print(">>> ReadWriteCharacteristic.WriteValue called")
        try:
            received_string = value.decode("utf-8")
            print(f"Client WRITE request received (RW Char). New value: {received_string}")
            self._value = value
        except UnicodeDecodeError:
            print("Error (RW Char): Received invalid UTF-8 data.")


class WifiScanCharacteristic(BleCharacteristic):
    """Custom implementation for the WiFi scan characteristic."""
    PATH = CHAR_SCAN_PATH

    def __init__(self, service_path: str):
        super().__init__(WIFI_SCAN_UUID, ["read"], service_path)

    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(">>> WifiScanCharacteristic.ReadValue called")
        print("Client READ request received (WiFi Scan Char). Starting scan...")
        loop = asyncio.get_running_loop()
        try:
            scan_result_dict = await loop.run_in_executor(None, run_wifi_scan)
            result_json = json.dumps(scan_result_dict)
            print(f"Sending scan result: {result_json}")
            return bytearray(result_json, "utf-8")
        except Exception as e:
            print(f"Error processing scan result in ReadValue: {e}")
            error_result = json.dumps({"error": f"Failed to process scan: {str(e)}"})
            return bytearray(error_result, "utf-8")

    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')

# --- Application Specific Descriptors ---

class UserDescriptionDescriptor(BleDescriptor):
    """Custom implementation for the Characteristic User Description descriptor."""
    # PATH needs to be set when instantiated

    def __init__(self, description: str, characteristic_path: str):
        super().__init__(USER_DESC_UUID, ["read"], characteristic_path)
        self._value = bytearray(description, "utf-8")
        self.PATH = characteristic_path + "/desc0" # Define path based on parent

    async def ReadValue(self, options: 'a{sv}') -> 'ay':
        print(f">>> UserDescriptionDescriptor.ReadValue called for {self._properties_dict['Characteristic']['value']}")
        return self._value

    async def WriteValue(self, value: 'ay', options: 'a{sv}'):
        # User Description is typically read-only
         raise DBusError('org.bluez.Error.NotPermitted', 'Write not permitted')


# --- Advertising Implementation ---
class BleAdvertisement(ServiceInterface):
    """
    org.bluez.LEAdvertisement1 interface implementation.
    """
    PATH = "/com/example/advertisement0"

    def __init__(self, ad_type: str, local_name: str, service_uuids: 'list[str]', appearance: int):
        super().__init__(LE_ADVERTISEMENT_IFACE)
        self._properties_dict = {}
        self._add_property("Type", ad_type, 's')
        self._add_property("LocalName", local_name, 's')
        self._add_property("ServiceUUIDs", service_uuids, 'as')
        self._add_property("Appearance", appearance, 'q')

    @method()
    def Release(self):
        print(f"Advertisement ({self.PATH}) released")

    def get_properties_for_om(self):
        return {name: self._get_property_variant(name) for name in self._properties_dict}


# --- Main Execution Logic ---
async def main():
    """
    Main asynchronous function to set up and run the BLE peripheral using direct D-Bus calls.
    """
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
    desc_rw = None # Descriptor objects
    desc_scan = None

    exported_paths = [] # Keep track of exported paths for cleanup

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
        if not adapter_path:
            raise Exception("Bluetooth adapter with GATT Manager not found.")

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
        char_rw = ReadWriteCharacteristic(service.PATH)
        char_scan = WifiScanCharacteristic(service.PATH)
        # Create descriptors
        desc_rw = UserDescriptionDescriptor("Read/Write Value", char_rw.PATH)
        desc_scan = UserDescriptionDescriptor("WiFi Scan Trigger/Result", char_scan.PATH)

        # Link descriptors to characteristics
        char_rw.add_descriptor_path(desc_rw.PATH)
        char_scan.add_descriptor_path(desc_scan.PATH)
        # Link characteristics to service
        service.add_characteristic_path(char_rw.PATH)
        service.add_characteristic_path(char_scan.PATH)

        # --- Prepare objects for GetManagedObjects ---
        print("Preparing objects for Object Manager...")
        app.add_object(service.PATH, service.get_interfaces_and_properties())
        app.add_object(char_rw.PATH, char_rw.get_interfaces_and_properties())
        app.add_object(char_scan.PATH, char_scan.get_interfaces_and_properties())
        # Add descriptors to the managed objects
        app.add_object(desc_rw.PATH, desc_rw.get_interfaces_and_properties())
        app.add_object(desc_scan.PATH, desc_scan.get_interfaces_and_properties())

        # --- Export objects onto D-Bus ---
        print("Exporting objects...")
        bus.export(APP_PATH, app); exported_paths.append(APP_PATH)
        bus.export(service.PATH, service); exported_paths.append(service.PATH)
        bus.export(char_rw.PATH, char_rw); exported_paths.append(char_rw.PATH)
        bus.export(char_scan.PATH, char_scan); exported_paths.append(char_scan.PATH)
        # Export descriptors
        bus.export(desc_rw.PATH, desc_rw); exported_paths.append(desc_rw.PATH)
        bus.export(desc_scan.PATH, desc_scan); exported_paths.append(desc_scan.PATH)
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

    except asyncio.CancelledError:
        print("Main task cancelled.")
    except DBusError as e:
         print(f"D-Bus Error occurred: {e.type} - {e.text}")
         traceback.print_exc()
    except Exception as e:
        print(f"An error occurred during setup or runtime: {e}")
        print("Traceback:")
        traceback.print_exc()

    finally:
        print("Shutting down...")
        # Unregister advertisement and application
        if bus and bus.connected:
            if ad_manager and advertisement:
                try:
                    print("Unregistering advertisement...")
                    await ad_manager.call_unregister_advertisement(advertisement.PATH)
                    print("Advertisement unregistered.")
                except DBusError as e:
                     if e.type != 'org.freedesktop.DBus.Error.UnknownObject' and e.type != 'org.bluez.Error.DoesNotExist':
                         print(f"D-Bus Error unregistering advertisement: {e.type} - {e.text}")
                except Exception as e:
                    print(f"Error unregistering advertisement: {e}")

            if gatt_manager and app:
                try:
                    print("Unregistering GATT application...")
                    await gatt_manager.call_unregister_application(APP_PATH)
                    print("GATT application unregistered.")
                except DBusError as e:
                     if e.type != 'org.freedesktop.DBus.Error.UnknownObject' and e.type != 'org.bluez.Error.DoesNotExist':
                         print(f"D-Bus Error unregistering application: {e.type} - {e.text}")
                except Exception as e:
                    print(f"Error unregistering application: {e}")

            # Unexport all paths
            print(f"Unexporting {len(exported_paths)} D-Bus objects...")
            for path in reversed(exported_paths): # Unexport in reverse order
                try:
                    bus.unexport(path)
                except Exception as e:
                    print(f"Error unexporting path {path}: {e}")
            print("D-Bus objects unexported.")

            print("Disconnecting from system bus...")
            bus.disconnect()
            print("Disconnected from system bus.")
        else:
            print("Bus connection was not established or already closed.")
        print("Shutdown complete.")


# Run the main asynchronous function
if __name__ == "__main__":
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
            try:
                loop.run_until_complete(main_task)
            except asyncio.CancelledError:
                pass
        if loop.is_running():
            loop.stop()
        if not loop.is_closed():
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
        print("Event loop closed.")


