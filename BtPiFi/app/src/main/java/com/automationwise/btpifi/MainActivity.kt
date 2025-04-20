package com.automationwise.btpifi

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.activity.compose.setContent

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme { // Uses default Material 3 colors/typography
                MainScreenContent()
            }
        }
    }
}

// This composable function defines the screen content
@Composable
fun MainScreenContent() {
    // Runs once when the composable first enters the composition
    LaunchedEffect(key1 = true) {
        Log.d("MainActivity", "Screen composed. Place initial logic trigger here.")
        // Example: Call function to start BLE scanning or setup
        // yourSetupFunction()
    }

    Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text("Ready for Logic")
            Spacer(modifier = Modifier.height(20.dp))
            Button(onClick = {
                Log.d("MainActivity", "Button Clicked! Place action logic trigger here.")
                // Example: Call your function to write to BLE
                // yourBleWriteFunction("data")
            }) {
                Text("Run Code")
            }
        }
    }
}

// ---  logic functions ---
// --- might call them from inside onClick or LaunchedEffect ---
// fun yourSetupFunction() { /* ... */ }
// fun yourBleWriteFunction(data: String) { /* ... */ }


// --- Android Studio Preview ---
// This helps visualize the UI without running on a device/emulator
@Preview(showBackground = true)
@Composable
fun DefaultPreview() {
    MaterialTheme {
        MainScreenContent()
    }

}