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
# Removed Characteristic/Descriptor Paths

SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
# Removed Characteristic/Descriptor UUIDs

DEVICE_NAME = "MyRPiDirectDBus-SvcOnly" # Modified name for test
BLUEZ_SERVICE = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE =      'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE =    'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
# Removed GATT_CHRC_IFACE, GATT_DESC_IFACE
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'


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

    # update_object_properties removed as it's not used in this simplified version

    @method()
    def GetManagedObjects(self) -> 'a{oa{sa{sv}}}':
        print("GetManagedObjects called")
        return self.managed_objects


class BaseGattInterface(ServiceInterface):
    """Base class for GATT Service interface."""
    # Simplified as it's only used by BleService now
    def __init__(self, interface_name):
        super().__init__(interface_name)
        self._properties_dict = {}

    def _add_property(self, name: str, value, signature: str, emit_signal=False):
        self._properties_dict[name] = {'value': value, 'signature': signature}

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
    Simplified: No Characteristics property needed for this test.
    """
    PATH = SERVICE_PATH

    def __init__(self, uuid: str, primary: bool):
        super().__init__(GATT_SERVICE_IFACE)
        self._add_property("UUID", uuid, 's')
        self._add_property("Primary", primary, 'b')
        # Removed Characteristics property

    # Removed add_characteristic_path method

    def get_interfaces_and_properties(self):
        """Returns interfaces and properties for Object Manager."""
        # Only return the GATT Service interface
        return { GATT_SERVICE_IFACE: self.get_properties_for_om() }


# --- Removed Characteristic and Descriptor Classes ---


# --- Advertising Implementation (Simplified) ---
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
    Main asynchronous function - Simplified to register only a service.
    """
    print(f"Starting Direct D-Bus BLE peripheral '{DEVICE_NAME}'...")
    bus = None
    adapter_path = None
    gatt_manager = None
    ad_manager = None
    app = None
    advertisement = None
    service = None
    # Removed char/desc variables

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
        if not adapter_path:
            raise Exception("Bluetooth adapter with GATT Manager not found.")

        # --- Get GATT Manager and Advertising Manager ---
        gatt_introspection = await bus.introspect(BLUEZ_SERVICE, adapter_path)
        adapter_object = bus.get_proxy_object(BLUEZ_SERVICE, adapter_path, gatt_introspection)
        gatt_manager = adapter_object.get_interface(GATT_MANAGER_IFACE)
        ad_manager = adapter_object.get_interface(LE_ADVERTISING_MANAGER_IFACE)
        print("Got GATT Manager and Advertising Manager interfaces.")

        # --- Create Application Objects (Service Only) ---
        print("Creating GATT objects (Service Only)...")
        app = Application(bus, APP_PATH)
        service = BleService(SERVICE_UUID, True)
        # No characteristics or descriptors created

        # --- Prepare objects for GetManagedObjects (Service Only) ---
        print("Preparing objects for Object Manager...")
        app.add_object(service.PATH, service.get_interfaces_and_properties())
        # No characteristics or descriptors added

        # --- Export objects onto D-Bus (Service Only) ---
        print("Exporting objects...")
        bus.export(APP_PATH, app); exported_paths.append(APP_PATH)
        bus.export(service.PATH, service); exported_paths.append(service.PATH)
        # No characteristics or descriptors exported
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

        print("Peripheral setup complete (Service Only). Running event loop (Press Ctrl+C to stop)...")
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
        # ... (Simplified shutdown logic) ...
        print("Shutting down...")
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

            if gatt_manager and app: # Check if app was created
                try:
                    print("Unregistering GATT application...")
                    await gatt_manager.call_unregister_application(APP_PATH)
                    print("GATT application unregistered.")
                except DBusError as e:
                     if e.type != 'org.freedesktop.DBus.Error.UnknownObject' and e.type != 'org.bluez.Error.DoesNotExist':
                         print(f"D-Bus Error unregistering application: {e.type} - {e.text}")
                except Exception as e:
                    print(f"Error unregistering application: {e}")

            print(f"Unexporting {len(exported_paths)} D-Bus objects...")
            for path in reversed(exported_paths):
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


