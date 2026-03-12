# Flashpoint

A PyQt6 GUI for flashing Qualcomm devices — supports parallel multi-device flashing, EDL mode, and an automated factory pipeline. Also ships a headless CLI for scripting.

## Features

- **Multi-device** — flash multiple devices simultaneously from a single window
- **EDL & ADB support** — works in both Emergency Download (EDL) and debug/user boot modes
- **USB port tracking** — identifies which physical port each device is connected to
- **Factory pipeline** — automated 3-stage flash sequence with boot verification and per-device pass/fail reports
- **Live progress** — per-device progress bars and inline log viewer
- **CLI** — headless `list`, `flash`, and `edl` commands for scripting

## Architecture

```
device.py        Device class — serial, mode, transport_id, usb_path, build_id
                 + adb(), reboot_to_edl(), flash_command()

scanner.py       scan_edl() / scan_adb() / scan_all() — returns Device objects
                 Serial is always the hardware _SN: from lsusb -v (stable across modes)

qdl_wrapper.py   Firmware file discovery and QDL command construction

pipeline.py      FactoryPipeline — pure state machine, no Qt/subprocess
                 Driven by the GUI (QTimer) or CLI (while loop)

app.py           Interactive flash station GUI
factory_app.py   Factory pipeline GUI — drives FactoryPipeline
flash.py         GUI entry point
cli.py           Headless CLI entry point
```

## Requirements

- Python 3.10+
- PyQt6
- `adb` on PATH
- [QDL](https://github.com/linux-msm/qdl) binary at `~/aio/qdl/qdl`

```bash
pip install -r requirements.txt
```

## USB Permissions (Linux)

EDL devices (`05c6:9008`) require udev access:

```bash
sudo nano /etc/udev/rules.d/99-qualcomm.rules
```

```
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## GUI Usage

### Standard mode

```bash
FW_PATH=/path/to/firmware python flash.py
```

`FW_PATH` should point to a directory containing:
- `prog*.elf` — Qualcomm firehose programmer
- `rawprogram*.xml`
- `patch*.xml`

### Factory mode

```bash
FACTORY_FW_PATH=/path/to/factory_fw \
PROD_DEBUG_FW_PATH=/path/to/prod_debug_fw \
python factory_app.py
```

The factory pipeline runs 3 stages per device:

1. **Flash 1/3** — initial firmware flash over EDL
2. **Boot** — device boots, build ID is verified against `EXPECTED_BUILD_ID`
3. **Flash 3/3** — reboots to EDL and flashes final image

Reports are saved to `FACTORY_REPORTS_DIR` (default: `~/factory_reports`).

## CLI Usage

```bash
# List all connected devices (serial, mode, ADB, build ID, USB path)
python cli.py list

# Flash firmware — defaults to all EDL devices, or specify serials
python cli.py flash /path/to/firmware
python cli.py flash /path/to/firmware ABC123 DEF456

# Reboot to EDL — defaults to all ADB-accessible devices, or specify serials
python cli.py edl
python cli.py edl ABC123
```

Multiple devices are flashed in parallel; each output line is prefixed with `[serial]`.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FW_PATH` | — | Firmware directory (standard GUI mode) |
| `FACTORY_FW_PATH` | — | Stage-1 factory firmware directory |
| `PROD_DEBUG_FW_PATH` | — | Stage-3 prod/debug firmware directory |
| `BOOT_TIMEOUT_SEC` | `120` | Seconds to wait for device to boot in factory pipeline |
| `FACTORY_REPORTS_DIR` | `~/factory_reports` | Output directory for factory session reports |
