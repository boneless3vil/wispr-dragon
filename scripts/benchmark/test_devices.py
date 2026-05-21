#!/usr/bin/env python3
import sounddevice as sd

print('Available audio devices:\n')
for i, device in enumerate(sd.query_devices()):
    print(f'{i}: {device["name"]}')
    print(f'   Input channels: {device["max_input_channels"]}')
    print(f'   Sample rate: {device["default_samplerate"]} Hz')
    print()
