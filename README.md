# Flashpoint

A PyQt6 GUI for flashing Qualcomm devices — supports parallel multi-device flashing, EDL mode, and an automated factory pipeline.

## Features

- **Multi-device** — flash multiple devices simultaneously from a single window
- **EDL & ADB support** — works in both Emergency Download (EDL) and debug/user boot modes
- **USB port tracking** — identifies which physical port each device is connected to
- **Factory pipeline** — automated 3-stage flash sequence with boot verification and per-device pass/fail reports
- **Live progress** — per-device progress bars and inline log viewer

## Requirements

- Python 3.10+
- PyQt6
- [QDL](https://github.com/linux-msm/qdl) binary at `~/aio/qdl/qdl`

```bash
pip install -r requirements.txt
```

## USB Permissions (Linux)

EDL devices (`05c6:9008`) require udev access. Create the rule:

```bash
sudo nano /etc/udev/rules.d/99-qualcomm.rules
```

```
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666"
```

Reload and replug:

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Verify with `~/aio/qdl/qdl list` — you should see device serials without needing sudo.

## Usage

### Standard mode

```bash
FW_PATH=/path/to/firmware python flash.py
```

Point `FW_PATH` at a directory containing:
- `prog*.elf` — Qualcomm firehose programmer
- `rawprogram*.xml`
- `patch*.xml`

### Factory mode

```bash
FACTORY_FW_PATH=/path/to/factory_fw \
PROD_DEBUG_FW_PATH=/path/to/prod_debug_fw \
FACTORY_REPORTS_DIR=~/factory_reports \
python factory_app.py
```

The factory pipeline runs automatically when a device is detected:

1. **Flash 1/3** — initial firmware flash over EDL
2. **Boot** — device boots, build ID is verified against `AQ3A.250226.002`
3. **Flash 3/3** — reboots to EDL and flashes final image

Results are saved as JSON reports in `FACTORY_REPORTS_DIR` (default: `~/factory_reports`).

| Env var | Default | Description |
|---|---|---|
| `FW_PATH` | — | Firmware directory (standard mode) |
| `FACTORY_FW_PATH` | — | Factory firmware directory |
| `PROD_DEBUG_FW_PATH` | — | Production debug firmware directory |
| `BOOT_TIMEOUT_SEC` | `120` | Seconds to wait for device to boot |
| `FACTORY_REPORTS_DIR` | `~/factory_reports` | Output directory for flash reports |
