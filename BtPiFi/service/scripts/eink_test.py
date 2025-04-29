#!/usr/bin/python3
# -*- coding:utf-8 -*-
import sys
import os
import logging
import time
import socket

# Assuming the waveshare_epd library is installed and accessible
# Adjust the path if you installed the library manually in a different location
# Example: libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
libdir = os.path.join(os.path.dirname(os.path.realpath('/home/eric/lib')), 'lib')
if os.path.exists(libdir):
     sys.path.append(libdir)

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # doesn't need to be reachable
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "No IP"

ip_address = get_ip()

# Import the specific display driver and Pillow libraries
from waveshare_epd import epd2in13_V4
from PIL import Image, ImageDraw, ImageFont

logging.basicConfig(level=logging.DEBUG)

try:
    logging.info("E-Ink Test Script Started")

    # Initialize the display driver for Waveshare 2.13inch V4
    epd = epd2in13_V4.EPD()

    logging.info("Initializing and clearing display...")
    # Initialize display - this sets up GPIO and SPI
    epd.init()
    # Clear the display to white
    epd.Clear(0xFF)
    logging.info("Display cleared.")
    time.sleep(1) # Give display time to clear

    # --- Create image content using Pillow ---
    logging.info("Creating image...")
    # Create a new black and white image (1-bit pixel)
    # Dimensions for 2.13 V4 are 122x250 (Width x Height)
    # Note: Pillow uses (width, height), but drawing might feel rotated
    # depending on how you hold the Pi/display. Let's assume standard orientation.
    image = Image.new('1', (epd.height, epd.width), 255) # 255: white background

    # Get a drawing object
    draw = ImageDraw.Draw(image)

    # Load a font
    # You might need to install fonts: sudo apt install fonts-freefont-ttf
    # Or provide a path to a specific .ttf file
    try:
        font15 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMono.ttf', 15)
        font24 = ImageFont.truetype('/usr/share/fonts/truetype/freefont/FreeMonoBold.ttf', 24)
    except IOError:
        logging.warning("Default font not found, using load_default()")
        font15 = ImageFont.load_default()
        font24 = ImageFont.load_default()

    # Draw some text
    # Coordinates are (x, y) from the top-left corner
    draw.text((10, 0), f'{ip_address}', font=font24, fill=0)
    draw.text((10, 80), 'Waiting for BLE...', font=font15, fill=0)

    # Draw a line
    draw.line([(0, 110), (epd.height, 110)], fill=0, width=2)

    logging.info("Displaying image...")
    # Display the image buffer on the e-ink screen
    # The library handles rotation if needed, but the image buffer should match dimensions
    epd.display(epd.getbuffer(image))
    time.sleep(2) # Give display time to update

    # --- Put the display to sleep ---
    logging.info("Putting display to sleep...")
    epd.sleep()
    logging.info("E-Ink Test Script Finished")

except IOError as e:
    logging.error(f"IOError: {e}")
    # Consider cleanup here if needed upon error

except KeyboardInterrupt:
    logging.info("Ctrl+C received, exiting...")
    # Ensure sleep mode is entered even if interrupted
    epd2in13_V4.epdconfig.module_exit(cleanup=True)
    exit()

except Exception as e:
    logging.error(f"An unexpected error occurred: {e}")
    epd2in13_V4.epdconfig.module_exit(cleanup=True)


