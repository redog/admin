#!/usr/bin/env python3

import asyncio
# Corrected import and usage for dbus-next asyncio
from dbus_next.aio import MessageBus
# Import BusType to specify the bus
from dbus_next import BusType
import traceback

async def test_dbus_connection():
    """
    Attempts to connect to the D-Bus system bus and prints the result.
    Uses the MessageBus class for connection, explicitly specifying SYSTEM bus.
    """
    print("Attempting to connect to D-Bus system bus using dbus-next...")
    bus = None
    try:
        # Corrected connection method: Instantiate MessageBus and connect.
        # Explicitly specify BusType.SYSTEM.
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        print("SUCCESS: Connected to D-Bus system bus.")

        # Optional: You could try a simple introspection here if needed later
        # print("Attempting introspection on org.freedesktop.DBus...")
        # introspection = await bus.introspect('org.freedesktop.DBus', '/')
        # print("SUCCESS: Introspection successful.")

    except asyncio.CancelledError:
        print("Operation cancelled.")
    except Exception as e:
        print(f"FAILURE: An error occurred during D-Bus connection or operation.")
        print(f"Error type: {type(e)}")
        print(f"Error details: {e}")
        print("Traceback:")
        traceback.print_exc()
    finally:
        if bus:
            # bus.disconnect() is not needed for MessageBus instances from connect()
            print("Bus connection will be closed automatically.")
        print("Test script finished.")

if __name__ == "__main__":
    print("Running minimal D-Bus connection test...")
    try:
        asyncio.run(test_dbus_connection())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt received.")
    except Exception as e:
        print(f"FAILURE: An error occurred running the asyncio loop.")
        print(f"Error type: {type(e)}")
        print(f"Error details: {e}")
        traceback.print_exc()


