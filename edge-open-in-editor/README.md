# Open in Editor Extension

## Overview

This browser extension allows you to open selected text in your preferred editor (defaults to Vim) directly from the browser. It works by sending the selected text to a native application, which then opens the editor.

## Features

- Opens selected text in the editor from the browser.
- Supports Vim as the default editor.
- Uses Alacritty as the default terminal.
- Only tested in Linux. TODO: test macOS, and Windows.

## Prerequisites

- **Browser:** Chromium-based browser (e.g., Chrome, Edge).
- **Editor:** Vim (or any editor of your choice, configurable in the Python script).
- **Terminal:** Alacritty (or any terminal emulator, configurable in the Python script).
- **Python:** Python 3.6 or higher.

## Installation

1.  **Install the Native Application**

    Clone the repository:

    ```bash
    git clone https://github.com/redog/admin/edge-open-in-editor.git
    cd edge-open-in-editor
    ```

    Copy the Python script:

    Copy `open_in_editor.py` to a suitable location (e.g., `~/.config/open_in_editor/open_in_editor.py`). Make sure the script is executable:

    ```bash
    mkdir -p ~/.config/open_in_editor
    cp open_in_editor.py ~/.config/open_in_editor/
    chmod +x ~/.config/open_in_editor/open_in_editor.py
    ```

2.  **Configure the Native Application Manifest**

    Copy the manifest file (`com.automationwise.openineditor.json`) from the `edge-open-in-editor/NativeMessagingHosts` directory to the appropriate directory for your browser:

    -   `~/.config/google-chrome/NativeMessagingHosts/`
    -   `~/.config/microsoft-edge/NativeMessagingHosts/`
    -   `~/.config/microsoft-edge-dev/NativeMessagingHosts/`

    **Important:**

    -   Ensure the `path` in the manifest file points to the actual location of your `open_in_editor.py` script.
    -   Update the `allowed_origins` in the manifest file with the ID of the extension. You can find this ID on the browser's extensions page (`chrome://extensions/` or `edge://extensions/`).

3.  **Install the Browser Extension**

    Load the extension files:

    -   Go to the extensions management page.
    -   Enable "Developer mode".
    -   Click "Load unpacked" and select the directory containing the extension files (`background.js`, `content.js`, and `manifest.json`).

## Usage

1.  Right-click on any selected text in a browser window.
2.  Select "Open in Editor" from the context menu.
3.  The selected text will open in your configured editor (Vim by default) in Alacritty.

## Configuration

### Python Script (`open_in_editor.py`)

-   **Editor:** To use a different editor, modify the `editor` variable in the `open_in_editor` function.
-   **Terminal:** To use a different terminal emulator, modify the `terminal` variable in the `open_in_editor` function.

### Browser Extension

-   **Extension ID in Manifest:** Ensure the `allowed_origins` in the native messaging manifest matches the ID of your installed browser extension.
