package com.automationwise.btpifi

// Replace with your package name

import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.* // Or material3
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.app.ActivityCompat
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            BTPiFiTheme { // Replace with your theme
                BleClientScreen()
            }
        }
    }
}

@Composable
fun BleClientScreen(bleViewModel: BleViewModel = viewModel()) {

    val context = LocalContext.current
    val scanResults by bleViewModel.scanResults.collectAsState()
    val isScanning by bleViewModel.isScanning.collectAsState()
    val connectionState by bleViewModel.connectionState.collectAsState()
    val errorMessage by bleViewModel.errorMessage.collectAsState()
    val readWriteValue by bleViewModel.readWriteValue.collectAsState()
    val wifiScanResult by bleViewModel.wifiScanResult.collectAsState()

    var rwValueToWrite by remember { mutableStateOf("") }
    var ssidToWrite by remember { mutableStateOf("") }
    var pskToWrite by remember { mutableStateOf("") }

    // --- Permission Handling ---
    val requiredPermissions = remember {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) { // Android 12+
            listOf(
                Manifest.permission.BLUETOOTH_SCAN,
                Manifest.permission.BLUETOOTH_CONNECT,
                Manifest.permission.ACCESS_FINE_LOCATION // Still needed for scan results with details
            )
        } else {
            listOf(
                Manifest.permission.BLUETOOTH,
                Manifest.permission.BLUETOOTH_ADMIN,
                Manifest.permission.ACCESS_FINE_LOCATION
            )
        }
    }
    var hasPermissions by remember { mutableStateOf(requiredPermissions.all { context.checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }) }

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        hasPermissions = permissions.values.all { it }
        if (!hasPermissions) {
            // Optional: Explain why permissions are needed or guide user to settings
            Log.w("BleClientScreen", "Not all permissions granted.")
        }
    }

    // Bluetooth Enable Intent Launcher
    val enableBluetoothLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == ComponentActivity.RESULT_OK) {
            // Bluetooth was enabled, maybe start scan automatically?
            Log.i("BleClientScreen", "Bluetooth Enabled")
        } else {
            // Bluetooth not enabled, user cancelled or error
            Log.w("BleClientScreen", "Bluetooth not enabled")
        }
    }

    // Request permissions when composable enters composition if not already granted
    LaunchedEffect(Unit) {
        if (!hasPermissions) {
            permissionLauncher.launch(requiredPermissions.toTypedArray())
        }
        // Check if Bluetooth is enabled
        val bluetoothManager = context.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
        if (bluetoothManager.adapter?.isEnabled == false) {
            // Request to enable Bluetooth
            val enableBtIntent = Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE)
            // Check if BLUETOOTH_CONNECT permission is granted before launching intent
            if (ActivityCompat.checkSelfPermission(context, Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED || Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
                enableBluetoothLauncher.launch(enableBtIntent)
            } else {
                Log.w("BleClientScreen", "Cannot request BT enable, BLUETOOTH_CONNECT permission missing")
                // You might want to request BLUETOOTH_CONNECT first if needed on API 31+
            }
        }
    }

    // --- UI ---
    Scaffold(
        topBar = { TopAppBar(title = { Text("BLE WiFi Config") }) }
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {

            // --- Permission Status ---
            if (!hasPermissions) {
                Text("Permissions needed for BLE operations.", color = MaterialTheme.colors.error)
                Button(onClick = {
                    // Guide user to app settings
                    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                    val uri = Uri.fromParts("package", context.packageName, null)
                    intent.data = uri
                    context.startActivity(intent)
                }) {
                    Text("Open App Settings")
                }
                Spacer(Modifier.height(16.dp))
            }

            // --- Scan Controls ---
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = { bleViewModel.startScan() },
                    enabled = !isScanning && hasPermissions && connectionState == BleConnectionState.DISCONNECTED
                ) { Text("Start Scan") }
                Spacer(Modifier.width(16.dp))
                Button(
                    onClick = { bleViewModel.stopScan() },
                    enabled = isScanning && hasPermissions
                ) { Text("Stop Scan") }
                Spacer(Modifier.width(16.dp))
                if (isScanning) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp))
                }
            }
            Spacer(Modifier.height(8.dp))

            // --- Connection Status & Error ---
            Text("Status: ${connectionState.name}")
            errorMessage?.let {
                Text("Error: $it", color = MaterialTheme.colors.error)
            }
            Spacer(Modifier.height(8.dp))

            // --- Scan Results ---
            if (scanResults.isNotEmpty() && connectionState == BleConnectionState.DISCONNECTED) {
                Text("Found Devices:", style = MaterialTheme.typography.h6)
                LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth()) {
                    items(scanResults) { device ->
                        DeviceItem(device = device) {
                            bleViewModel.connectToDevice(device)
                        }
                    }
                }
            } else if (connectionState != BleConnectionState.DISCONNECTED) {
                // --- Connected Controls ---
                ConnectedDeviceControls(
                    bleViewModel,
                    rwValueToWrite,
                    { rwValueToWrite = it },
                    ssidToWrite,
                    { ssidToWrite = it },
                    pskToWrite,
                    { pskToWrite = it })
            } else if (!isScanning) {
                Text("Press 'Start Scan' to find devices.")
            }

            // --- Disconnect Button ---
            if (connectionState != BleConnectionState.DISCONNECTED) {
                Spacer(Modifier.height(16.dp))
                Button(onClick = { bleViewModel.disconnect() }) {
                    Text("Disconnect")
                }
            }
        }
    }
}

@Composable
fun DeviceItem(device: BleDevice, onClick: () -> Unit) {
    Card(modifier = Modifier
        .fillMaxWidth()
        .padding(vertical = 4.dp)
        .clickable(onClick = onClick),
        elevation = 2.dp
    ) {
        Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(text = device.name ?: "Unknown Device", style = MaterialTheme.typography.body1)
            Spacer(Modifier.weight(1f))
            Text(text = device.address, style = MaterialTheme.typography.caption)
        }
    }
}

@Composable
fun ConnectedDeviceControls(
    bleViewModel: BleViewModel,
    rwValue: String, onRwValueChanged: (String) -> Unit,
    ssidValue: String, onSsidValueChanged: (String) -> Unit,
    pskValue: String, onPskValueChanged: (String) -> Unit
) {
    val readWriteValue by bleViewModel.readWriteValue.collectAsState()
    val wifiScanResult by bleViewModel.wifiScanResult.collectAsState()

    Column(modifier = Modifier.fillMaxWidth()) {
        Text("Connected Controls", style = MaterialTheme.typography.h6)
        Spacer(Modifier.height(16.dp))

        // --- Read/Write Characteristic ---
        Text("Read/Write Characteristic (${BleConstants.CHAR_READ_WRITE_UUID.toString().takeLast(4)})")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Button(onClick = { bleViewModel.readReadWriteCharacteristic() }) { Text("Read") }
            Spacer(Modifier.width(8.dp))
            Text("Value: $readWriteValue")
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = rwValue,
                onValueChange = onRwValueChanged,
                label = { Text("Value to Write") },
                modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { bleViewModel.writeReadWriteCharacteristic(rwValue) }) { Text("Write") }
        }
        Spacer(Modifier.height(16.dp))

        // --- WiFi Scan Characteristic ---
        Text("WiFi Scan Characteristic (${BleConstants.WIFI_SCAN_UUID.toString().takeLast(4)})")
        Button(onClick = { bleViewModel.readWifiScanCharacteristic() }) { Text("Scan WiFi") }
        Spacer(Modifier.height(8.dp))
        Text("Result: $wifiScanResult") // Display raw JSON for now
        Spacer(Modifier.height(16.dp))

        // --- Set SSID Characteristic ---
        Text("Set SSID Characteristic (${BleConstants.WIFI_SET_SSID_UUID.toString().takeLast(4)})")
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = ssidValue,
                onValueChange = onSsidValueChanged,
                label = { Text("SSID to Set") },
                modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { bleViewModel.writeSsidCharacteristic(ssidValue) }) { Text("Write SSID") }
        }
        Spacer(Modifier.height(16.dp))

        // --- Set PSK Characteristic ---
        Text("Set PSK Characteristic (${BleConstants.WIFI_SET_PSK_UUID.toString().takeLast(4)})")
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = pskValue,
                onValueChange = onPskValueChanged,
                label = { Text("PSK to Set") },
                modifier = Modifier.weight(1f)
            )
            Spacer(Modifier.width(8.dp))
            Button(onClick = { bleViewModel.writePskCharacteristic(pskValue) }) { Text("Write PSK") }
        }
    }
}