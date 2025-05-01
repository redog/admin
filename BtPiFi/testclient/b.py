import asyncio
from bleak import BleakClient, BleakScanner, BleakError

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
    try:
        devices = await BleakScanner.discover()

        target_device = None
        for device in devices:
            print(f"Found: {device.name}, {device.address}")
            if device.name and "BtPiFi" in device.name:
                print(f"   ^ Found target device!")
                target_device = device
                break

        if not target_device:
            print("Target BLE device not found!")
            return

        # Attempting to connect to the target device
        async with BleakClient(target_device, timeout=30.0) as client:
            connected = await client.is_connected()
            if connected:
                print(f"Connected to {target_device.name}, Address: {target_device.address}")

                try:
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
                except BleakError as e:
                    print(f"BleakError encountered while interacting with characteristics: {e}")
                except Exception as e:
                    print(f"Error during BLE operations: {e}")
            else:
                print("Failed to connect to the BLE device.")

    except BleakError as e:
        print(f"Bleak scanning error: {e}")
    except Exception as e:
        print(f"Error during scanning: {e}")

async def main():
    await scan_and_connect()

if __name__ == '__main__':
    asyncio.run(main())
