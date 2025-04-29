'use strict';

const bleno = require('bleno');
const util = require('util');
const { exec } = require('child_process'); // For calling Python scripts

// --- Configuration ---
// Reuse the same UUIDs
const SERVICE_UUID = "133934e0-01f5-4054-a88f-0136e064c49e";
const CMD_CHAR_UUID = "133934e1-01f5-4054-a88f-0136e064c49e"; // Write
const STATUS_CHAR_UUID = "133934e2-01f5-4054-a88f-0136e064c49e"; // Read, Notify
const SSID_CHAR_UUID = "133934e3-01f5-4054-a88f-0136e064c49e"; // Read, Notify

const PERIPHERAL_NAME = "PiWifiConfig";

// --- Global State ---
let currentStatus = "Idle";
let scannedSsidsJson = "[]";
let statusUpdateCallback = null; // For characteristic notifications
let ssidsUpdateCallback = null; // For characteristic notifications

console.log(`Starting ${PERIPHERAL_NAME} service...`);

// --- Helper for calling Python ---
// Promisify exec for easier async/await usage
const execPromise = util.promisify(exec);

async function runPythonScript(scriptPath, args = []) {
    // Basic security: escape arguments to prevent injection if needed
    const escapedArgs = args.map(arg => `'${String(arg).replace(/'/g, "'\\''")}'`).join(' ');
    const command = `python3 ${scriptPath} ${escapedArgs}`;
    console.log(`Executing: ${command}`);
    try {
        const { stdout, stderr } = await execPromise(command);
        if (stderr) {
            console.error(`Python script stderr (${scriptPath}): ${stderr}`);
        }
        console.log(`Python script stdout (${scriptPath}): ${stdout.trim()}`);
        return stdout.trim(); // Return standard output
    } catch (error) {
        console.error(`Error executing Python script (${scriptPath}): ${error}`);
        throw error; // Re-throw error to be handled by caller
    }
}

// --- Characteristic Implementations ---

// Command Characteristic (Write)
class WifiCommandCharacteristic extends bleno.Characteristic {
    constructor() {
        super({
            uuid: CMD_CHAR_UUID,
            properties: ['write', 'writeWithoutResponse'],
            value: null,
            descriptors: [
                new bleno.Descriptor({
                    uuid: '2901', // Characteristic User Description
                    value: 'Receives Wi-Fi commands (SCAN, CONNECT|ssid|pwd)'
                })
            ]
        });
        this._value = Buffer.alloc(0);
    }

    onWriteRequest(data, offset, withoutResponse, callback) {
        this._value = data;
        const command = this._value.toString('utf-8').trim();
        console.log(`WifiCommandCharacteristic - onWriteRequest: value = ${this._value.toString('hex')} (${command})`);

        // Handle command asynchronously
        this.handleCommand(command).then(() => {
             callback(this.RESULT_SUCCESS);
        }).catch((error) => {
             console.error("Command handling failed:", error);
             // Optionally update status characteristic to reflect error
             updateStatus("Error: Cmd Failed");
             callback(this.RESULT_UNLIKELY_ERROR); // Or appropriate error code
        });
    }

    async handleCommand(command) {
        console.log(`Handling command: ${command}`);
        if (command.toUpperCase() === "SCAN") {
            updateStatus("Scanning...");
            try {
                // TODO: Replace 'scripts/wifi_scan.py' with your actual script path
                const stdout = await runPythonScript('scripts/wifi_scan.py');
                // Assuming python script prints a JSON list of SSIDs
                updateScannedSsids(stdout || "[]"); // Update with result or empty list
                updateStatus("Scan Complete");
            } catch (error) {
                updateStatus("Error: Scan Failed");
            }
        } else if (command.toUpperCase().startsWith("CONNECT")) {
            const parts = command.split('|');
            if (parts.length === 3) {
                const [, ssid, password] = parts;
                updateStatus(`Connecting to ${ssid}...`);
                try {
                     // TODO: Replace 'scripts/wifi_connect.py' with your actual script path
                    const stdout = await runPythonScript('scripts/wifi_connect.py', [ssid, password]);
                    // Assuming python script prints status (e.g., "Connected", "Failed")
                    updateStatus(stdout || "Error: Connect Failed"); // Update with result
                } catch (error) {
                    updateStatus("Error: Connect Failed");
                }
            } else {
                console.warn("Invalid CONNECT command format");
                updateStatus("Error: Invalid Cmd");
            }
        } else {
            console.warn(`Unknown command: ${command}`);
            updateStatus("Error: Unknown Cmd");
        }
    }
}

// Status Characteristic (Read, Notify)
class WifiStatusCharacteristic extends bleno.Characteristic {
    constructor() {
        super({
            uuid: STATUS_CHAR_UUID,
            properties: ['read', 'notify'],
            value: null, // Initial value updated on subscribe/read
             descriptors: [
                new bleno.Descriptor({
                    uuid: '2901', // Characteristic User Description
                    value: 'Current status of the Wi-Fi connection process'
                })
            ]
        });
        this._value = Buffer.from(currentStatus);
    }

    onReadRequest(offset, callback) {
        console.log(`WifiStatusCharacteristic - onReadRequest. Current status: ${currentStatus}`);
        this._value = Buffer.from(currentStatus); // Update buffer before reading
        callback(this.RESULT_SUCCESS, this._value.slice(offset, this._value.length));
    }

    onSubscribe(maxValueSize, updateValueCallback) {
        console.log('WifiStatusCharacteristic - onSubscribe');
        statusUpdateCallback = updateValueCallback; // Store the callback for notifications
    }

    onUnsubscribe() {
        console.log('WifiStatusCharacteristic - onUnsubscribe');
        statusUpdateCallback = null;
    }

    // Helper to send notification
    sendNotification(value) {
         this._value = Buffer.from(value);
         if (statusUpdateCallback) {
            console.log(`WifiStatusCharacteristic - sending notification: ${value} (${this._value.toString('hex')})`);
            statusUpdateCallback(this._value);
         } else {
             console.log('WifiStatusCharacteristic - no subscriber to notify.');
         }
    }
}

// Scanned SSIDs Characteristic (Read, Notify)
class ScannedSsidsCharacteristic extends bleno.Characteristic {
    constructor() {
        super({
            uuid: SSID_CHAR_UUID,
            properties: ['read', 'notify'],
            value: null, // Initial value updated on subscribe/read
             descriptors: [
                new bleno.Descriptor({
                    uuid: '2901', // Characteristic User Description
                    value: 'JSON list of scanned Wi-Fi SSIDs'
                })
            ]
        });
        this._value = Buffer.from(scannedSsidsJson);
    }

     onReadRequest(offset, callback) {
        console.log(`ScannedSsidsCharacteristic - onReadRequest.`);
        this._value = Buffer.from(scannedSsidsJson); // Update buffer before reading
        // TODO: Handle offset and potential chunking for large lists if needed
        callback(this.RESULT_SUCCESS, this._value.slice(offset, this._value.length));
    }

    onSubscribe(maxValueSize, updateValueCallback) {
        console.log('ScannedSsidsCharacteristic - onSubscribe');
        ssidsUpdateCallback = updateValueCallback; // Store the callback for notifications
    }

    onUnsubscribe() {
        console.log('ScannedSsidsCharacteristic - onUnsubscribe');
        ssidsUpdateCallback = null;
    }

     // Helper to send notification
    sendNotification(value) {
         this._value = Buffer.from(value);
         if (ssidsUpdateCallback) {
            console.log(`ScannedSsidsCharacteristic - sending notification: ${value}`);
             // TODO: Handle potential chunking for large lists if MTU is too small
            ssidsUpdateCallback(this._value);
         } else {
             console.log('ScannedSsidsCharacteristic - no subscriber to notify.');
         }
    }
}

// Instantiate characteristics
const wifiCommandCharacteristic = new WifiCommandCharacteristic();
const wifiStatusCharacteristic = new WifiStatusCharacteristic();
const scannedSsidsCharacteristic = new ScannedSsidsCharacteristic();

// --- Update Functions (call these to change state and notify) ---
function updateStatus(newStatus) {
    if (newStatus !== currentStatus) {
        console.log(`Updating status from "${currentStatus}" to "${newStatus}"`);
        currentStatus = newStatus;
        wifiStatusCharacteristic.sendNotification(currentStatus);
        // TODO: Call python script to update e-ink display
        // runPythonScript('scripts/eink_update.py', ['status', currentStatus]).catch(err => console.error("E-ink update failed:", err));
    }
}

function updateScannedSsids(newSsidsJson) {
     if (newSsidsJson !== scannedSsidsJson) {
        console.log(`Updating SSIDs`);
        scannedSsidsJson = newSsidsJson;
        scannedSsidsCharacteristic.sendNotification(scannedSsidsJson);
     }
}

// --- Bleno Event Handlers ---

bleno.on('stateChange', function(state) {
    console.log('on -> stateChange: ' + state);
    if (state === 'poweredOn') {
        // Start advertising
        bleno.startAdvertising(PERIPHERAL_NAME, [SERVICE_UUID], function(err) {
            if (err) {
                console.error("Advertising error:", err);
            }
        });
    } else {
        console.log('Stopping advertising.');
        bleno.stopAdvertising();
    }
});

bleno.on('advertisingStart', function(error) {
    console.log('on -> advertisingStart: ' + (error ? 'error ' + error : 'success'));
    if (!error) {
        // Define the service and characteristics
        bleno.setServices([
            new bleno.PrimaryService({
                uuid: SERVICE_UUID,
                characteristics: [
                    wifiCommandCharacteristic,
                    wifiStatusCharacteristic,
                    scannedSsidsCharacteristic
                ]
            })
        ], function(err) {
            console.log('setServices: ' + (err ? 'error ' + err : 'success'));
        });
    }
});

bleno.on('advertisingStop', function() {
    console.log('on -> advertisingStop');
});

bleno.on('servicesSet', function(error) {
     console.log('on -> servicesSet: ' + (error ? 'error ' + error : 'success'));
});

bleno.on('accept', function(clientAddress) {
    console.log(`Client connected: ${clientAddress}`);
    // Optionally stop advertising when a client connects? Or allow multiple?
    // bleno.stopAdvertising();
});

bleno.on('disconnect', function(clientAddress) {
     console.log(`Client disconnected: ${clientAddress}`);
     // Optionally restart advertising if stopped on connect
     // bleno.startAdvertising(...);
});

// --- Graceful Shutdown ---
process.on('SIGINT', function() {
    console.log("\nCaught interrupt signal. Shutting down gracefully.");
    bleno.stopAdvertising(() => {
        console.log("Advertising stopped.");
        // Optional: Disconnect clients? Bleno might handle this.
        process.exit(0);
    });
});

// Initial status update (optional)
// updateStatus("Initializing"); // Or keep "Idle"


