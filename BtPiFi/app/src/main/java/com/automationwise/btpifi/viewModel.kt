package com.automationwise.btpifi

import android.Manifest
import android.annotation.SuppressLint
import android.app.Application
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.ParcelUuid
import android.util.Log
import androidx.core.app.ActivityCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch

// Represents a found BLE device
data class BleDevice(
    val name: String?,
    val address: String,
    val device: BluetoothDevice
)

// Represents the different states of the BLE connection
enum class BleConnectionState {
    DISCONNECTED, CONNECTING, CONNECTED, FAILED, DISCOVERING
}

@SuppressLint("MissingPermission") // Permissions handled at UI layer
class ViewModel(application: Application) : AndroidViewModel(application) {

    private val TAG = "ViewModel"
    private val bluetoothManager = application.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager.adapter

    // --- State Flows for UI ---
    private val _scanResults = MutableStateFlow<List<BleDevice>>(emptyList())
    val scanResults: StateFlow<List<BleDevice>> = _scanResults.asStateFlow()

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    private val _connectionState = MutableStateFlow(BleConnectionState.DISCONNECTED)
    val connectionState: StateFlow<BleConnectionState> = _connectionState.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    // --- Data from Characteristics ---
    private val _readWriteValue = MutableStateFlow<String>("")
    val readWriteValue: StateFlow<String> = _readWriteValue.asStateFlow()

    private val _wifiScanResult = MutableStateFlow<String>("") // Store raw JSON for now
    val wifiScanResult: StateFlow<String> = _wifiScanResult.asStateFlow()

    // --- Internal BLE State ---
    private var scanner: BluetoothLeScanner? = null
    private var bluetoothGatt: BluetoothGatt? = null
    private val foundDevices = mutableMapOf<String, BleDevice>() // Address -> BleDevice
    private var scanJob: Job? = null
    private var connectJob: Job? = null

    // Store references to characteristics once discovered
    private var readWriteCharacteristic: BluetoothGattCharacteristic? = null
    private var wifiScanCharacteristic: BluetoothGattCharacteristic? = null
    private var setSsidCharacteristic: BluetoothGattCharacteristic? = null
    private var setPskCharacteristic: BluetoothGattCharacteristic? = null


    // --- Scanning Logic ---
    private val scanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult?) {
            result?.device?.let { device ->
                // Check permissions before accessing name (needed for Android 12+)
                if (hasPermission(Manifest.permission.BLUETOOTH_CONNECT)) {
                    val name = device.name ?: "Unknown"
                    val address = device.address
                    if (!foundDevices.containsKey(address)) {
                        Log.d(TAG, "Device found: $name ($address)")
                    }
                    // Add or update device
                    foundDevices[address] = BleDevice(name, address, device)
                    _scanResults.value = foundDevices.values.toList().sortedBy { it.name ?: "zzz" }
                } else {
                    Log.w(TAG,"BLUETOOTH_CONNECT permission missing, cannot get device name")
                    // Handle case where name cannot be retrieved due to permissions
                    val address = device.address
                    if (!foundDevices.containsKey(address)) {
                        Log.d(TAG, "Device found: address $address (name requires permission)")
                        foundDevices[address] = BleDevice("Name N/A", address, device)
                        _scanResults.value = foundDevices.values.toList().sortedBy { it.name ?: "zzz" }
                    }
                }
            }
        }

        override fun onBatchScanResults(results: MutableList<ScanResult>?) {
            results?.forEach { onScanResult(ScanSettings.CALLBACK_TYPE_ALL_MATCHES, it) }
        }

        override fun onScanFailed(errorCode: Int) {
            Log.e(TAG, "Scan failed with error code: $errorCode")
            _errorMessage.value = "Scan failed: $errorCode"
            _isScanning.value = false
        }
    }

    fun startScan() {
        if (!hasPermission(Manifest.permission.BLUETOOTH_SCAN)) {
            _errorMessage.value = "BLUETOOTH_SCAN permission needed."
            return
        }
        if (!isBleEnabled()) {
            _errorMessage.value = "Bluetooth is not enabled."
            return
        }

        if (_isScanning.value) return // Already scanning

        Log.d(TAG, "Starting BLE Scan...")
        _errorMessage.value = null
        foundDevices.clear()
        _scanResults.value = emptyList()
        _isScanning.value = true
        scanner = bluetoothAdapter?.bluetoothLeScanner

        // Scan filter for our specific service UUID
        val scanFilter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(BleConstants.SERVICE_UUID))
            .build()
        val scanSettings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY) // Use low latency for active scanning
            .build()

        scanner?.startScan(listOf(scanFilter), scanSettings, scanCallback)

        // Stop scan after a period (e.g., 15 seconds)
        scanJob?.cancel()
        scanJob = viewModelScope.launch {
            delay(15000)
            if (_isScanning.value) {
                stopScan()
            }
        }
    }

    fun stopScan() {
        if (!hasPermission(Manifest.permission.BLUETOOTH_SCAN)) {
            _errorMessage.value = "BLUETOOTH_SCAN permission needed to stop scan."
            // Still attempt to change state
            _isScanning.value = false
            scanJob?.cancel()
            return
        }
        if (!_isScanning.value) return

        Log.d(TAG, "Stopping BLE Scan...")
        scanner?.stopScan(scanCallback)
        _isScanning.value = false
        scanJob?.cancel()
    }

    // --- Connection Logic ---
    private val gattCallback = object : BluetoothGattCallback() {
        override fun onConnectionStateChange(gatt: BluetoothGatt?, status: Int, newState: Int) {
            val deviceAddress = gatt?.device?.address ?: "Unknown Address"
            Log.d(TAG, "onConnectionStateChange: Address=$deviceAddress, Status=$status, NewState=$newState")

            if (status == BluetoothGatt.GATT_SUCCESS) {
                when (newState) {
                    BluetoothProfile.STATE_CONNECTED -> {
                        Log.i(TAG, "Connected to GATT server $deviceAddress.")
                        _connectionState.value = BleConnectionState.CONNECTED
                        // Discover services after successful connection
                        viewModelScope.launch(Dispatchers.IO) {
                            delay(600) // Short delay before discovery sometimes helps
                            Log.i(TAG,"Attempting service discovery...")
                            _connectionState.value = BleConnectionState.DISCOVERING
                            val discoveryInitiated = gatt?.discoverServices()
                            if (discoveryInitiated == false) {
                                Log.e(TAG, "Failed to initiate service discovery.")
                                _errorMessage.value = "Failed to start service discovery"
                                disconnect() // Disconnect if discovery fails to start
                            }
                        }
                    }
                    BluetoothProfile.STATE_DISCONNECTED -> {
                        Log.i(TAG, "Disconnected from GATT server $deviceAddress.")
                        disconnect() // Clean up resources
                    }
                }
            } else {
                Log.e(TAG, "GATT Connection Error: Status=$status for $deviceAddress")
                _errorMessage.value = "Connection Error: $status"
                disconnect() // Clean up on error
                _connectionState.value = BleConnectionState.FAILED
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt?, status: Int) {
            Log.d(TAG, "onServicesDiscovered: Status=$status")
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "Services discovered successfully.")
                _connectionState.value = BleConnectionState.CONNECTED // Back to connected state
                // Find characteristics we care about
                val service = gatt?.getService(BleConstants.SERVICE_UUID)
                if (service == null) {
                    Log.e(TAG, "Target service (${BleConstants.SERVICE_UUID}) not found!")
                    _errorMessage.value = "Target Service not found"
                    disconnect()
                    return
                }
                readWriteCharacteristic = service.getCharacteristic(BleConstants.CHAR_READ_WRITE_UUID)
                wifiScanCharacteristic = service.getCharacteristic(BleConstants.WIFI_SCAN_UUID)
                setSsidCharacteristic = service.getCharacteristic(BleConstants.WIFI_SET_SSID_UUID)
                setPskCharacteristic = service.getCharacteristic(BleConstants.WIFI_SET_PSK_UUID)

                Log.d(TAG, "Read/Write Char found: ${readWriteCharacteristic != null}")
                Log.d(TAG, "WiFi Scan Char found: ${wifiScanCharacteristic != null}")
                Log.d(TAG, "Set SSID Char found: ${setSsidCharacteristic != null}")
                Log.d(TAG, "Set PSK Char found: ${setPskCharacteristic != null}")

                if (readWriteCharacteristic == null || wifiScanCharacteristic == null || setSsidCharacteristic == null || setPskCharacteristic == null) {
                    Log.e(TAG, "One or more required characteristics not found!")
                    _errorMessage.value = "Required characteristic(s) not found"
                    // Optionally disconnect, or allow partial functionality
                } else {
                    _errorMessage.value = null // Clear previous errors on successful discovery
                }

            } else {
                Log.w(TAG, "Service discovery failed with status: $status")
                _errorMessage.value = "Service discovery failed: $status"
                disconnect()
            }
        }

        // Called when characteristic read operation completes
        override fun onCharacteristicRead(
            gatt: BluetoothGatt,
            characteristic: BluetoothGattCharacteristic,
            value: ByteArray, // Deprecated in API 33+
            status: Int
        ) {
            // Note: For API 33+, use the other onCharacteristicRead callback
            handleCharacteristicRead(characteristic, value, status)
        }

        // Called when characteristic write operation completes
        override fun onCharacteristicWrite(
            gatt: BluetoothGatt?,
            characteristic: BluetoothGattCharacteristic?,
            status: Int
        ) {
            Log.d(TAG, "onCharacteristicWrite: UUID=${characteristic?.uuid}, Status=$status")
            if (status == BluetoothGatt.GATT_SUCCESS) {
                Log.i(TAG, "Characteristic ${characteristic?.uuid} written successfully.")
                // Optionally provide feedback to UI
            } else {
                Log.w(TAG, "Characteristic ${characteristic?.uuid} write failed: $status")
                _errorMessage.value = "Write failed: $status"
            }
        }

        // --- Helper to handle read results (called by both callback versions) ---
        private fun handleCharacteristicRead(characteristic: BluetoothGattCharacteristic, value: ByteArray?, status: Int) {
            val uuid = characteristic.uuid
            Log.d(TAG, "onCharacteristicRead: UUID=$uuid, Status=$status")
            if (status == BluetoothGatt.GATT_SUCCESS) {
                if (value != null) {
                    val stringValue = try { value.toString(Charsets.UTF_8) } catch (e: Exception) { value.toHexString() }
                    Log.i(TAG, "Read characteristic $uuid: \"$stringValue\"")
                    viewModelScope.launch(Dispatchers.Main) {
                        when (uuid) {
                            BleConstants.CHAR_READ_WRITE_UUID -> _readWriteValue.value = stringValue
                            BleConstants.WIFI_SCAN_UUID -> _wifiScanResult.value = stringValue // Store raw JSON
                            // Add cases for other readable characteristics if any
                        }
                    }
                } else {
                    Log.w(TAG, "Read characteristic $uuid: Value is null")
                }
            } else {
                Log.w(TAG, "Read characteristic $uuid failed: $status")
                _errorMessage.value = "Read failed: $status"
            }
        }
    } // End of gattCallback


    fun connectToDevice(device: BleDevice) {
        if (!hasPermission(Manifest.permission.BLUETOOTH_CONNECT)) {
            _errorMessage.value = "BLUETOOTH_CONNECT permission needed."
            return
        }
        if (_connectionState.value != BleConnectionState.DISCONNECTED) {
            Log.w(TAG, "Already connected or connecting.")
            return
        }

        stopScan() // Stop scanning before connecting
        _connectionState.value = BleConnectionState.CONNECTING
        _errorMessage.value = null
        Log.i(TAG, "Connecting to ${device.address}...")

        connectJob?.cancel() // Cancel previous connection attempts
        connectJob = viewModelScope.launch(Dispatchers.IO) {
            try {
                bluetoothGatt = device.device.connectGatt(getApplication(), false, gattCallback, BluetoothDevice.TRANSPORT_LE)
                if (bluetoothGatt == null) {
                    Log.e(TAG, "connectGatt returned null for ${device.address}")
                    _errorMessage.value = "Failed to initiate connection"
                    _connectionState.value = BleConnectionState.FAILED
                }
                // Connection result handled in gattCallback.onConnectionStateChange
            } catch (e: Exception) {
                Log.e(TAG, "Exception during connectGatt: ${e.message}", e)
                _errorMessage.value = "Connection exception: ${e.message}"
                _connectionState.value = BleConnectionState.FAILED
            }
        }
    }

    fun disconnect() {
        Log.d(TAG, "Disconnect called")
        if (!hasPermission(Manifest.permission.BLUETOOTH_CONNECT)) {
            _errorMessage.value = "BLUETOOTH_CONNECT permission needed to disconnect."
            // Still try to clean up internal state
            bluetoothGatt?.close()
            bluetoothGatt = null
            _connectionState.value = BleConnectionState.DISCONNECTED
            clearCharacteristics()
            return
        }
        connectJob?.cancel()
        bluetoothGatt?.disconnect() // Trigger disconnection
        bluetoothGatt?.close()      // Release resources
        bluetoothGatt = null
        _connectionState.value = BleConnectionState.DISCONNECTED
        clearCharacteristics()
        Log.i(TAG, "Disconnected and resources released.")
    }

    private fun clearCharacteristics() {
        readWriteCharacteristic = null
        wifiScanCharacteristic = null
        setSsidCharacteristic = null
        setPskCharacteristic = null
        _readWriteValue.value = ""
        _wifiScanResult.value = ""
    }

    // --- Characteristic Interaction ---

    fun readReadWriteCharacteristic() {
        if (!checkConnectionAndPermission("Read RW Char")) return
        readWriteCharacteristic?.let { char ->
            val success = bluetoothGatt?.readCharacteristic(char) ?: false
            Log.d(TAG, "Initiating read for Read/Write Char: $success")
            if (!success) _errorMessage.value = "Failed to initiate read RW Char"
        } ?: run { _errorMessage.value = "Read/Write Characteristic not found" }
    }

    fun readWifiScanCharacteristic() {
        if (!checkConnectionAndPermission("Read WiFi Scan Char")) return
        wifiScanCharacteristic?.let { char ->
            val success = bluetoothGatt?.readCharacteristic(char) ?: false
            Log.d(TAG, "Initiating read for WiFi Scan Char: $success")
            if (!success) _errorMessage.value = "Failed to initiate read WiFi Scan Char"
        } ?: run { _errorMessage.value = "WiFi Scan Characteristic not found" }
    }

    fun writeReadWriteCharacteristic(value: String) {
        if (!checkConnectionAndPermission("Write RW Char")) return
        readWriteCharacteristic?.let { char ->
            if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) == 0 &&
                (char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) == 0) {
                _errorMessage.value = "RW Characteristic does not support write"
                return@let
            }
            // Set write type based on characteristic properties
            char.writeType = if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0) {
                BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT // Write with response
            } else {
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE // Write without response
            }

            val bytesToSend = value.toByteArray(Charsets.UTF_8)
            // For Android 13+ use the new writeCharacteristic method
            val success = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                bluetoothGatt?.writeCharacteristic(char, bytesToSend, char.writeType) == BluetoothStatusCodes.SUCCESS
            } else {
                // Use deprecated method for older versions
                @Suppress("DEPRECATION")
                char.value = bytesToSend
                @Suppress("DEPRECATION")
                bluetoothGatt?.writeCharacteristic(char) ?: false
            }

            Log.d(TAG, "Initiating write for RW Char: $success")
            if (!success) _errorMessage.value = "Failed to initiate write RW Char"
        } ?: run { _errorMessage.value = "Read/Write Characteristic not found" }
    }

    fun writeSsidCharacteristic(ssid: String) {
        if (!checkConnectionAndPermission("Write SSID Char")) return
        setSsidCharacteristic?.let { char ->
            if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) == 0 &&
                (char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) == 0) {
                _errorMessage.value = "Set SSID Characteristic does not support write"
                return@let
            }
            char.writeType = if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0) {
                BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            } else {
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            }

            val bytesToSend = ssid.toByteArray(Charsets.UTF_8)
            val success = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                bluetoothGatt?.writeCharacteristic(char, bytesToSend, char.writeType) == BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                char.value = bytesToSend
                @Suppress("DEPRECATION")
                bluetoothGatt?.writeCharacteristic(char) ?: false
            }
            Log.d(TAG, "Initiating write for Set SSID Char: $success")
            if (!success) _errorMessage.value = "Failed to initiate write Set SSID Char"
        } ?: run { _errorMessage.value = "Set SSID Characteristic not found" }
    }

    fun writePskCharacteristic(psk: String) {
        if (!checkConnectionAndPermission("Write PSK Char")) return
        setPskCharacteristic?.let { char ->
            if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) == 0 &&
                (char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE) == 0) {
                _errorMessage.value = "Set PSK Characteristic does not support write"
                return@let
            }
            char.writeType = if ((char.properties and BluetoothGattCharacteristic.PROPERTY_WRITE) != 0) {
                BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            } else {
                BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE
            }

            val bytesToSend = psk.toByteArray(Charsets.UTF_8)
            val success = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                bluetoothGatt?.writeCharacteristic(char, bytesToSend, char.writeType) == BluetoothStatusCodes.SUCCESS
            } else {
                @Suppress("DEPRECATION")
                char.value = bytesToSend
                @Suppress("DEPRECATION")
                bluetoothGatt?.writeCharacteristic(char) ?: false
            }
            Log.d(TAG, "Initiating write for Set PSK Char: $success")
            if (!success) _errorMessage.value = "Failed to initiate write Set PSK Char"
        } ?: run { _errorMessage.value = "Set PSK Characteristic not found" }
    }


    // --- Helpers ---
    private fun checkConnectionAndPermission(operation: String): Boolean {
        if (!hasPermission(Manifest.permission.BLUETOOTH_CONNECT)) {
            _errorMessage.value = "BLUETOOTH_CONNECT permission needed for $operation."
            return false
        }
        if (bluetoothGatt == null || _connectionState.value != BleConnectionState.CONNECTED) {
            _errorMessage.value = "Not connected to device for $operation."
            return false
        }
        return true
    }

    private fun hasPermission(permission: String): Boolean {
        return ActivityCompat.checkSelfPermission(
            getApplication(),
            permission
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun isBleEnabled(): Boolean {
        return bluetoothAdapter?.isEnabled == true
    }

    override fun onCleared() {
        super.onCleared()
        Log.d(TAG, "ViewModel cleared, disconnecting...")
        disconnect() // Ensure cleanup when ViewModel is destroyed
    }

    // Extension function for logging byte arrays as hex
    fun ByteArray.toHexString(): String = joinToString(separator = " ", prefix = "0x") { "%02X".format(it) }

}