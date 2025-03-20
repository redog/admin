#!/usr/bin/env python3

import sys
import json
import subprocess
import os
import struct
import tempfile

def get_message_length():
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        sys.exit(0)
    message_length = struct.unpack('<I', raw_length)[0]
    return message_length

def read_native_message(length):
    message = sys.stdin.buffer.read(length)
    decoded_message = message.decode('utf-8')
    return decoded_message

def send_native_message(message):
    encoded_content = json.dumps(message).encode('utf-8')
    encoded_length = struct.pack('<I', len(encoded_content))
    sys.stdout.buffer.write(encoded_length)
    sys.stdout.buffer.write(encoded_content)
    sys.stdout.flush()

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

        vim_command = [terminal, '-e', editor, temp_file_path]
        process = subprocess.Popen(vim_command)
        process.wait()
        return f"Text opened in {editor} via {terminal}."
    except Exception as e:
        return f"Error opening Vim in terminal: {str(e)}"

def main():
    try:
        message_length = get_message_length()
        if message_length <= 0:
            sys.exit(1)

        message_json = read_native_message(message_length)
        message = json.loads(message_json)

        if 'text' in message:
            text = message['text']
            response_message = open_in_editor(text)
            send_native_message({"result": response_message})
        else:
            error_msg = "No text received."
            send_native_message({"status": "error", "message": error_msg})

    except Exception as e:
        send_native_message({"status": "error", "message": str(e)})

if __name__ == "__main__":
    main()

