import asyncio
import logging
import sys
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- Configuration (Should match the server script) ---
# Use the UUIDs defined in your ble_service_revised script
TARGET_SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
CMD_CHAR_UUID = "133934e1-01f5-4054-a88f-0136e064c49e" # Write
STATUS_CHAR_UUID = "133934e2-01f5-4054-a88f-0136e064c49e" # Read, Notify
SSID_CHAR_UUID = "133934e3-01f5-4054-a88f-0136e064c49e" # Read, Notify

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logging.getLogger("bleak.backends.winrt.client").setLevel(logging.WARNING) # Quieten bleak's verbose logging

# --- Notification Handlers ---
def handle_status_notification(sender_handle: int, data: bytearray):
    """Handles notifications received from the Status characteristic."""
    decoded_data = data.decode('utf-8', errors='replace')
    logger.info(f"[STATUS NOTIFY] Handle: {sender_handle}, Data: '{decoded_data}'")

def handle_ssid_notification(sender_handle: int, data: bytearray):
    """Handles notifications received from the SSID characteristic."""
    decoded_data = data.decode('utf-8', errors='replace')
    logger.info(f"[SSID NOTIFY]   Handle: {sender_handle}, Data: '{decoded_data}'")

async def run_ble_client():
    """Scans for the target device, connects, and interacts with it."""
    target_device = None
    logger.info("Scanning for devices advertising our service...")

    # Scan for devices advertising the specific service UUID
    devices = await BleakScanner.discover(service_uuids=[TARGET_SERVICE_UUID], timeout=10.0)

    if not devices:
        logger.error(f"Could not find device advertising service {TARGET_SERVICE_UUID}")
        return

    # Assuming the first found device is the target
    # In a real scenario, you might filter by name or address if multiple devices advertise the same UUID
    target_device = devices[0]
    logger.info(f"Found target device: {target_device.name} ({target_device.address})")

    # Create a client instance and connect
    async with BleakClient(target_device.address) as client:
        if not client.is_connected:
            logger.error(f"Failed to connect to {target_device.address}")
            return

        logger.info(f"Connected to {client.address}")

        try:
            # --- Read Initial Values ---
            logger.info("Reading initial Status...")
            status_value_bytes = await client.read_gatt_char(STATUS_CHAR_UUID)
            logger.info(f"Initial Status: '{status_value_bytes.decode('utf-8', errors='replace')}'")

            logger.info("Reading initial SSIDs...")
            ssid_value_bytes = await client.read_gatt_char(SSID_CHAR_UUID)
            logger.info(f"Initial SSIDs: '{ssid_value_bytes.decode('utf-8', errors='replace')}'")

            # --- Enable Notifications ---
            logger.info("Enabling Status notifications...")
            await client.start_notify(STATUS_CHAR_UUID, handle_status_notification)

            logger.info("Enabling SSID notifications...")
            await client.start_notify(SSID_CHAR_UUID, handle_ssid_notification)

            logger.info("Notifications enabled. Ready to send command.")
            await asyncio.sleep(1.0) # Short pause

            # --- Write Command ---
            command_to_send = "SCAN"
            logger.info(f"Writing command '{command_to_send}' to command characteristic...")
            await client.write_gatt_char(CMD_CHAR_UUID, command_to_send.encode('utf-8'), response=False) # Use write without response
            logger.info("Command sent.")

            # --- Keep Running to Receive Notifications ---
            logger.info("Client running. Waiting for notifications... Press Ctrl+C to exit.")
            # Keep the script alive to receive notifications
            while client.is_connected:
                await asyncio.sleep(1.0) # Check connection status periodically

        except BleakError as e:
            logger.error(f"BleakError during operation: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        finally:
            if client.is_connected:
                logger.info("Disabling notifications...")
                try:
                    await client.stop_notify(STATUS_CHAR_UUID)
                    await client.stop_notify(SSID_CHAR_UUID)
                except BleakError as e:
                    logger.warning(f"Error disabling notifications (might be disconnected already): {e}")
                logger.info("Disconnecting...")
            else:
                 logger.info("Client already disconnected.")


async def main():
    await run_ble_client()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client stopped by user.")
    except Exception as e:
         logger.error(f"Unhandled exception in main: {e}", exc_info=True)

