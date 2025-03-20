#!/usr/bin/env python3

import sys
import json
import subprocess
import os
import struct
import tempfile
import logging

# Configure logging
logging.basicConfig(
    filename='/tmp/open_in_editor.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def get_message_length():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        sys.exit(0)  # Exit if no message.
    message_length = struct.unpack('<I', raw_length)[0]  # Little-endian
    return message_length

def read_native_message(length):
    message = sys.stdin.buffer.read(length)
    decoded_message = message.decode('utf-8')
    logging.debug(f"Decoded Message JSON: {decoded_message}")
    return decoded_message

def send_native_message(message):
    try:
        encoded_content = json.dumps(message).encode('utf-8')
        encoded_length = struct.pack('<I', len(encoded_content))  # Little-endian
        sys.stdout.buffer.write(encoded_length)
        sys.stdout.buffer.write(encoded_content)
        sys.stdout.flush()
        logging.debug(f"Sent Message: {message}")
    except Exception as e:
        logging.error(f"Failed to send message: {e}")

def open_in_editor(text):
    """Opens the given text in Vim in Alacritty."""
    terminal = 'alacritty'
    editor = os.environ.get('EDITOR')
    if not editor or 'vim' not in editor.lower():
        editor = 'vim'
    try:
        with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as tmp_file:
            tmp_file.write(text)
            temp_file_path = tmp_file.name
            logging.debug(f"Temporary file created at: {temp_file_path}")

        # Open Vim with the temporary file in Alacritty
        vim_command = [terminal, '-e', editor, temp_file_path]
        logging.debug(f"Executing command: {' '.join(vim_command)}")
        process = subprocess.Popen(vim_command)
        process.wait()
        logging.debug(f"Editor process exited with return code: {process.returncode}")
        return f"Text opened in {editor} via {terminal}."
    except Exception as e:
        logging.error(f"Error opening Vim in terminal: {e}")
        return f"Error opening Vim in terminal: {str(e)}"

def main():
    try:
        message_length = get_message_length()
        logging.debug(f"Message Length: {message_length}")

        if message_length <= 0:
            logging.error("Received invalid message length.")
            sys.exit(1)

        message_json = read_native_message(message_length)
        message = json.loads(message_json)

        logging.debug(f"Parsed Message: {message}")

        if 'text' in message:
            text = message['text']
            logging.debug(f"Text to open: {repr(text)}")  # Use repr to visualize special characters
            response_message = open_in_editor(text)
            send_native_message({"result": response_message})
        else:
            error_msg = "No text received."
            logging.error(error_msg)
            send_native_message({"status": "error", "message": error_msg})

    except Exception as e:
        logging.error(f"Exception in main: {e}")
        send_native_message({"status": "error", "message": str(e)})

if __name__ == "__main__":
    main()
