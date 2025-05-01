import asyncio
from bleak import BleakClient, BleakScanner

# UUIDs from your GATT server
SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e"
CHAR_READ_WRITE_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"
WIFI_SCAN_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"
WIFI_SET_SSID_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"
WIFI_SET_PSK_UUID = "133934e4-01f5-4054-a88f-0136e064c49e"
WIFI_CONNECT_UUID = "133934e5-01f5-4054-a88f-0136e064c49e"

async def scan_and_connect():
    # Perform a scan to find your device
    print("Scanning for devices...")
    devices = await BleakScanner.discover()

    # Find and print the target device
    target_device = None
    for device in devices:
        # Print device info regardless of name
        print(f"Found: {device.name}, {device.address}")
        # Check if device.name is not None before checking its content
        if device.name is not None and "BtPiFi" in device.name:
            print(f"   ^ Found target device!")
            target_device = device
            break # Found it, stop scanning

    if not target_device:
        print("Target BLE device not found!")
        return

    async with BleakClient(target_device, timeout=30.0) as client:
        print(f"Connected to {target_device.name}, Address: {target_device.address}")

        # Interacting with the RW Characteristic
        print("Reading RW Characteristic...")
        rw_value = await client.read_gatt_char(CHAR_READ_WRITE_UUID)
        print(f"Current RW Value: {rw_value.decode('utf-8', errors='ignore')}")

        # Trigger Wi-Fi scan characteristic
        print("Reading WiFi Scan Characteristic...")
        scan_result = await client.read_gatt_char(WIFI_SCAN_UUID)
        print(f"WiFi Scan Result: {scan_result.decode('utf-8', errors='ignore')}")

        # Writing target SSID
        test_ssid = "Ericnet"
        await client.write_gatt_char(WIFI_SET_SSID_UUID, bytearray(test_ssid, 'utf-8'))
        print(f"Wrote SSID: {test_ssid}")

        # Writing target PSK
        test_psk = "goodluck"
        await client.write_gatt_char(WIFI_SET_PSK_UUID, bytearray(test_psk, 'utf-8'))
        print(f"Wrote PSK: {test_psk}")

        # Trigger connection
        print("Triggering connection...")
        await client.write_gatt_char(WIFI_CONNECT_UUID, bytearray(b'trigger'))

async def main():
    await scan_and_connect()

if __name__ == '__main__':
    asyncio.run(main())
