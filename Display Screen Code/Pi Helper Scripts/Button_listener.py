#!/usr/bin/env python3
from gpiozero import Button
from signal import pause
import subprocess

# Initialize buttons using correct BCM numbering
start_button = Button(24, pull_up=True)
shutdown_button = Button(16, pull_up=True)  # GPIO16 corresponds to physical pin 36

def on_start_button_pressed():
    print("Start button pressed! Launching PiRudderTach...")
    subprocess.Popen(["/usr/bin/python3", "/home/mikestrohofer/Scripts/PiRudderTach.py"])

def on_shutdown_pressed():
    print("Shutdown button pressed! Initiating shutdown...")
    subprocess.call(["sudo", "shutdown", "-h", "now"])

# Assign callbacks to the buttons
start_button.when_pressed = on_start_button_pressed
shutdown_button.when_pressed = on_shutdown_pressed

# Keep the script running to listen for events
pause()
