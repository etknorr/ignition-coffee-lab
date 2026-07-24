# Quick Start Guide

Get your ICL Roast Monitor up and running in minutes.

## Prerequisites

Before starting, ensure you have:

- Raspberry Pi Pico W
- MAX31855 thermocouple amplifier
- Type K thermocouple probe
- Micro-USB cable
- Computer with USB port

## Step 1: Install CircuitPython

1. Download CircuitPython 9.0+ for Pico W from [circuitpython.org/board/raspberry_pi_pico_w](https://circuitpython.org/board/raspberry_pi_pico_w/)
2. Hold the **BOOTSEL** button on your Pico W while connecting USB
3. Copy the `.uf2` file to the `RPI-RP2` drive that appears
4. The Pico will reboot and mount as `CIRCUITPY`

## Step 2: Wire the Hardware

Connect your components according to this pinout:

| Pico W Pin | MAX31855 Pin | Function           |
|------------|--------------|---------------------|
| GP18       | SCK          | SPI Clock           |
| GP16       | SO (MISO)    | SPI Data Out        |
| GP17       | CS           | Chip Select         |
| 3V3        | VCC          | 3.3V Power          |
| GND        | GND          | Ground              |

```
 Pico W                    MAX31855
┌──────────┐              ┌──────────┐
│ GP18 ────┼──────────────┼─▶ SCK    │
│ GP16 ◀───┼──────────────┼── SO     │
│ GP17 ────┼──────────────┼─▶ CS     │
│ 3V3  ────┼──────────────┼─▶ VCC    │
│ GND  ────┼──────────────┼─▶ GND    │
└──────────┘              │          │
                          │ T+ ──┐   │
                          │ T- ──┘   │ ◀── Type K Thermocouple
                          └──────────┘
```

## Step 3: Install Project Files

```bash
# Clone the repository
git clone https://github.com/etknorr/ignition-coffee-lab.git
cd ignition-coffee-lab

# Copy files to your Pico W
cp -r raspberry-pi-pico/* /Volumes/CIRCUITPY/
```

> **Note**: On Windows, the drive is typically `D:` or `E:`. On Linux, check `/media/username/CIRCUITPY`.

## Step 4: Configure WiFi

Edit `settings.toml` on your CIRCUITPY drive:

```toml
# Required: WiFi credentials
WIFI_SSID = "YourNetworkName"
WIFI_PASSWORD = "YourPassword"

# Optional: Enable CircuitPython Web Workflow for remote access
CIRCUITPY_WIFI_SSID = "YourNetworkName"
CIRCUITPY_WIFI_PASSWORD = "YourPassword"
CIRCUITPY_WEB_API_PASSWORD = "your_api_password"
```

## Step 5: Choose Your Output Mode

Edit `main.py` to select how temperature data is sent:

```python
# Choose one:
OUTPUT_MODE = "artisan"   # For Artisan Scope roast profiling
# OUTPUT_MODE = "mqtt"    # For SCADA/automation systems
# OUTPUT_MODE = "console" # For debugging (serial output only)

# Temperature unit for single-unit outputs
PREFERRED_TEMP_UNIT = "F"  # or "C"
```

## Step 6: Connect and Test

1. **Reset the Pico W** (unplug and replug USB, or press reset button)
2. **Watch the LED**:
   - Short-short-pause pattern = connecting to WiFi
   - 3 blinks then solid = connected successfully
   - Quick blinks = sending temperature data
3. **Open serial console** to see output:

   ```bash
   # macOS/Linux
   screen /dev/tty.usbmodem* 115200

   # Exit with: Ctrl+A, then K, then Y
   ```

You should see:

```
╔══════════════════════════════════════════════════════╗
║              IGNITION COFFEE LAB                     ║
║                 Roast Monitor v1.0                   ║
╚══════════════════════════════════════════════════════╝

INFO: Thermocouple ready - Current: 23.5°C
INFO: WiFi already connected - IP: 192.168.1.100
INFO: Artisan server listening on 192.168.1.100:8765
```

## Next Steps

### For Artisan Scope Users

1. Open Artisan Scope
2. Go to **Config** → **Device** → **WebSocket**
3. Enter URL: `ws://[pico_ip]:8765` (use IP from serial output)
4. Set **BT (Bean Temperature)** to **input1**
5. Click **ON** to connect

### For MQTT/SCADA Users

Configure your MQTT broker in `settings.toml`:

```toml
MQTT_BROKER = "192.168.1.50"
MQTT_PORT = "1883"
MQTT_TEMP_TOPIC = "icl/roast_monitor/pico01/temperature"
```

## Troubleshooting

| Problem | LED Pattern | Solution |
|---------|-------------|----------|
| Won't connect to WiFi | Fast blinking | Check SSID/password in settings.toml |
| No temperature readings | Fast blinking | Check thermocouple wiring |
| Artisan can't connect | Normal operation | Verify IP address and port 8765 |

For detailed troubleshooting, see the [main README](../README.md#troubleshooting).

## Getting Help

- Enable debug mode: Set `DEBUG_MODE = True` in `main.py`
- Check serial output for detailed error messages
- See [GitHub Issues](https://github.com/etknorr/ignition-coffee-lab/issues) for known issues
