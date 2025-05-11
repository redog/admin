import asyncio
import logging
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# UUIDs from the BLE service
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
CHAR_READ_WRITE_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"
WIFI_SCAN_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"
WIFI_SET_SSID_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"
WIFI_SET_PSK_UUID = "133934e4-01f5-4054-a88f-0136e064c49e"

# Configuration
MAX_SCAN_ATTEMPTS = 30
SCAN_TIMEOUT = 10.0  # seconds
CONNECTION_TIMEOUT = 30.0  # seconds
RETRY_DELAY = 1.0  # seconds between retries
CHAR_OPERATION_RETRIES = 3  # number of retries for characteristic operations
CHAR_OPERATION_DELAY = 2.0  # increased delay between characteristic operation retries
CONNECTION_STABILIZATION_DELAY = 2.0  # seconds to wait after connection
WIFI_SCAN_WAIT = 13.0  # seconds to wait for WiFi scan to complete

def get_device_info(device):
    """Safely extract device information, handling different formats"""
    try:
        # Handle the case where device might be a string or other format
        if not hasattr(device, '__dict__'):
            return None, None, None

        # Try to get name
        name = None
        if hasattr(device, 'name'):
            if device.name is None:
                name = "Unknown"
            elif hasattr(device.name, 'name'):  # macOS specific
                name = device.name.name
            else:
                name = str(device.name)

        # Try to get address
        address = None
        if hasattr(device, 'address'):
            address = str(device.address)

        # Try to get RSSI
        rssi = None
        if hasattr(device, 'rssi'):
            rssi = device.rssi

        return name, address, rssi
    except Exception as e:
        logger.debug(f"Error getting device info: {e}")
        return None, None, None

def log_device_info(device):
    """Log detailed information about a discovered device"""
    try:
        name, address, rssi = get_device_info(device)
        if name is None and address is None:
            return  # Skip devices we can't get info from

        # Log all device info for debugging
        logger.info(f"Device: {name or 'Unknown'}")
        if address:
            logger.info(f"  Address: {address}")
        if rssi is not None:
            logger.info(f"  RSSI: {rssi}")
        if hasattr(device, 'metadata') and device.metadata:
            logger.info(f"  Metadata: {device.metadata}")
        if hasattr(device, 'advertisement_data') and device.advertisement_data:
            adv_data = device.advertisement_data
            logger.info(f"  Advertisement Data:")
            if hasattr(adv_data, 'manufacturer_data'):
                logger.info(f"    Manufacturer Data: {adv_data.manufacturer_data}")
            if hasattr(adv_data, 'service_data'):
                logger.info(f"    Service Data: {adv_data.service_data}")
            if hasattr(adv_data, 'service_uuids'):
                logger.info(f"    Service UUIDs: {adv_data.service_uuids}")
            if hasattr(adv_data, 'local_name'):
                logger.info(f"    Local Name: {adv_data.local_name}")
    except Exception as e:
        logger.debug(f"Error logging device info: {e}")

async def scan_for_device():
    """Scan for the BtPiFi device with retries"""
    for attempt in range(MAX_SCAN_ATTEMPTS):
        logger.info(f"Scanning for BtPiFi device (attempt {attempt + 1}/{MAX_SCAN_ATTEMPTS})...")
        
        try:
            # Simple scan with no filters
            devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT)
            logger.info(f"Found {len(devices)} devices in scan")
            
            # Log all discovered devices
            for device in devices:
                name = device.name or "Unknown"
                address = device.address
                logger.info(f"Found device: {name} ({address})")
                
                # Check if this is our target device
                if name and ("btpifi" in name.lower() or "raspberrypi" in name.lower()):
                    logger.info(f"Found target device: {name} ({address})")
                    return device
            
            if attempt < MAX_SCAN_ATTEMPTS - 1:
                logger.warning(f"No target device found, retrying in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)
                
        except Exception as e:
            logger.error(f"Error during scan attempt {attempt + 1}: {e}")
            if attempt < MAX_SCAN_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_DELAY)
    
    logger.error("Target device not found after all attempts!")
    return None

async def connect_with_retry(device, max_attempts=3):
    """Attempt to connect to the device with retries"""
    for attempt in range(max_attempts):
        try:
            logger.info(f"Attempting to connect (attempt {attempt + 1}/{max_attempts})...")
            client = BleakClient(device.address, timeout=CONNECTION_TIMEOUT)
            await client.connect()
            return client
        except BleakError as e:
            logger.error(f"Connection attempt {attempt + 1} failed: {e}")
            if attempt < max_attempts - 1:
                logger.info(f"Retrying in {RETRY_DELAY} seconds...")
                await asyncio.sleep(RETRY_DELAY)
            else:
                raise

async def read_characteristic_with_retry(client, char_uuid, description=""):
    """Read a characteristic with retries"""
    for attempt in range(CHAR_OPERATION_RETRIES):
        try:
            if description:
                logger.info(f"Reading {description}...")
            value = await client.read_gatt_char(char_uuid)
            return value.decode('utf-8', errors='ignore')
        except BleakError as e:
            logger.error(f"Read attempt {attempt + 1} failed: {e}")
            if attempt < CHAR_OPERATION_RETRIES - 1:
                wait_time = CHAR_OPERATION_DELAY * (attempt + 1)  # Increase delay with each retry
                logger.info(f"Retrying read in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                raise

async def write_characteristic_with_retry(client, char_uuid, value, description=""):
    """Write to a characteristic with retries"""
    for attempt in range(CHAR_OPERATION_RETRIES):
        try:
            if description:
                logger.info(f"Writing {description}...")
            await client.write_gatt_char(char_uuid, value)
            return True
        except BleakError as e:
            logger.error(f"Write attempt {attempt + 1} failed: {e}")
            if attempt < CHAR_OPERATION_RETRIES - 1:
                logger.info(f"Retrying write in {CHAR_OPERATION_DELAY} seconds...")
                await asyncio.sleep(CHAR_OPERATION_DELAY)
            else:
                raise

async def interact_with_device(device):
    """Interact with the BLE device"""
    client = None
    try:
        # Connect with retry
        client = await connect_with_retry(device)
        logger.info(f"Connected to {device.name}")
        
        # Wait for connection to stabilize
        logger.info(f"Waiting {CONNECTION_STABILIZATION_DELAY} seconds for connection to stabilize...")
        await asyncio.sleep(CONNECTION_STABILIZATION_DELAY)
        
        # 1. Read initial value from Read/Write characteristic
        initial_value = await read_characteristic_with_retry(
            client, 
            CHAR_READ_WRITE_UUID,
            "initial value from Read/Write characteristic"
        )
        logger.info(f"Initial value: {initial_value}")
        
        # 2. Trigger WiFi scan
        await write_characteristic_with_retry(
            client,
            CHAR_READ_WRITE_UUID,
            b'SCAN',
            "SCAN command to Read/Write characteristic"
        )
        
        # Wait for scan to complete
        logger.info(f"Waiting {WIFI_SCAN_WAIT} seconds for WiFi scan to complete...")
        await asyncio.sleep(WIFI_SCAN_WAIT)
        
        # 3. Read WiFi scan results - only try once since we know the scan is complete
        try:
            logger.info("Reading WiFi scan results...")
            value = await client.read_gatt_char(WIFI_SCAN_UUID)
            scan_results = value.decode('utf-8', errors='ignore')
            logger.info(f"Scan results: {scan_results}")
        except BleakError as e:
            logger.error(f"Failed to read scan results: {e}")
            return
        
        # 4. Set WiFi credentials
        ssid = "YourWiFiSSID"
        psk = "YourWiFiPassword"
        
        await write_characteristic_with_retry(
            client,
            WIFI_SET_SSID_UUID,
            ssid.encode('utf-8'),
            f"SSID: {ssid}"
        )
        
        await write_characteristic_with_retry(
            client,
            WIFI_SET_PSK_UUID,
            psk.encode('utf-8'),
            f"PSK: {psk}"
        )
        
        # 5. Trigger connection
        await write_characteristic_with_retry(
            client,
            CHAR_READ_WRITE_UUID,
            b'CONNECT',
            "CONNECT command to Read/Write characteristic"
        )
        
        # Wait for connection attempt
        logger.info("Waiting for connection attempt...")
        await asyncio.sleep(5)
        
        # 6. Read final status
        final_status = await read_characteristic_with_retry(
            client,
            CHAR_READ_WRITE_UUID,
            "final status"
        )
        logger.info(f"Final status: {final_status}")
        
    except BleakError as e:
        logger.error(f"BLE error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        if client and client.is_connected:
            try:
                await client.disconnect()
                logger.info("Disconnected from device")
            except Exception as e:
                logger.error(f"Error during disconnect: {e}")

async def main():
    device = await scan_for_device()
    if device:
        await interact_with_device(device)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Client stopped by user")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}") 