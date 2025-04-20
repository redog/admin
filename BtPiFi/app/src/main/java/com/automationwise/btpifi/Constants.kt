package com.automationwise.btpifi

import java.util.UUID

object BleConstants {
    // Service UUID from Pi script
    val SERVICE_UUID: UUID = UUID.fromString("12345678-1234-5678-1234-56789abcdef0")
    // Characteristic UUIDs from Pi script
    val CHAR_READ_WRITE_UUID: UUID = UUID.fromString("12345678-1234-5678-1234-56789abcdef1")
    val WIFI_SCAN_UUID: UUID = UUID.fromString("12345678-1234-5678-1234-56789abcdef2")
    val WIFI_SET_SSID_UUID: UUID = UUID.fromString("12345678-1234-5678-1234-56789abcdef3")
    val WIFI_SET_PSK_UUID: UUID = UUID.fromString("12345678-1234-5678-1234-56789abcdef4")
    // Descriptor UUID (Standard CUD)
    val USER_DESC_UUID: UUID = UUID.fromString("00002901-0000-1000-8000-00805f9b34fb") // Standard CUD UUID
}