# Qualcomm Flash Station — Go Rewrite Reference

This document covers everything needed to rewrite the flash station GUI in Go:
device detection via `lsusb` and sysfs, the `qdl` binary interface, ADB
integration, firmware file layout, and the flashing lifecycle.

---

## 1. Device Modes and USB IDs

Every device appears on the USB bus with a specific vendor:product ID that
tells you which mode it is in. All detection is built on these IDs.

| Mode         | VID:PID   | Meaning                                    |
|--------------|-----------|--------------------------------------------|
| EDL          | 05c6:9008 | Emergency Download — ready to flash        |
| USER BOOTED  | 18d1:4ee1 | Fully booted user build, ADB available     |
| DEBUG BOOTED | 18d1:4e11 | Fully booted debug build, ADB available    |
| DEBUG BOOTED | 05c6:901f | Alternate debug PID, ADB available         |

The mode drives everything: which UI controls are enabled, what actions are
available, and whether a device can be flashed right now.

---

## 2. Device Detection via lsusb

### 2.1 Plain lsusb — enumerate what is connected

Run `lsusb` with no arguments. Example output:

```
Bus 001 Device 003: ID 05c6:9008 Qualcomm, Inc. DLOAD
Bus 001 Device 007: ID 18d1:4e11 Google Inc. Nexus/Pixel Device
```

Parse each line for a known VID:PID. Regex to extract bus, device number,
and the ID:

```
Bus (\d+) Device (\d+): ID ([\da-f]{4}:[\da-f]{4})
```

From a matched line you get:
- `bus`    — e.g. `001`
- `devnum` — e.g. `003`
- `vidpid` — e.g. `05c6:9008` — determines the mode

In Go, run `exec.Command("lsusb")`, capture stdout, iterate lines.

### 2.2 lsusb -v — read the serial number

Once you have bus and devnum, run:

```
sudo lsusb -v -s 001:003
```

This dumps the full USB descriptor for that specific device. The serial number
is in the `iSerial` field:

```
  iSerial                 3 _SN:A1B2C3D4
```

Parse with:

```
_SN:([0-9a-fA-F]+)
```

The captured group — `A1B2C3D4` — is the hardware serial. It is used as the
device key in the map, displayed in the UI table, and passed as the `-S`
argument to qdl.

**Root requirement:** `lsusb -v` needs permission to open the USB device node
(`/dev/bus/usb/BUS/DEV`) to read string descriptors. Without root or a udev
rule, `iSerial` comes back empty or the call fails entirely. Run it with sudo,
or configure udev (see section 9).

**Race condition:** A device that just entered EDL mode appears in plain `lsusb`
almost immediately (kernel registers it), but its USB descriptor may not be
ready yet for `lsusb -v` to read. If `lsusb -v` returns no `iSerial`, fall
back to sysfs (section 3). This is the root cause of the "failed to read
iProduct" errors in the original `qdl list` approach — `qdl list` uses libusb
which has the same problem, while sysfs reads work at kernel level before the
device is fully enumerable.

### 2.3 Full per-tick scan procedure

Run this on a ticker every ~1500ms:

1. Run `lsusb`, collect lines matching any known VID:PID.
2. For each line, extract bus and devnum.
3. Resolve the USB path string from sysfs using bus + devnum (section 3.1).
4. Run `sudo lsusb -v -s BUS:DEV`, parse `iSerial` for the serial number.
5. If iSerial is empty or the call fails, fall back to sysfs serial (section 3.2).
6. Determine mode from the VID:PID.
7. If mode is USER or DEBUG BOOTED, query ADB for transport ID and build ID (section 4).
8. Diff results against the current device map. Add new, update existing, remove stale.

---

## 3. sysfs — USB Path and Serial Fallback

The kernel exposes every USB device under `/sys/bus/usb/devices/`. Each entry
is a directory named by its USB topology position, e.g. `3-1`, `3-1.2`,
`3-1.2.4`.

### 3.1 Resolving the USB path from bus + devnum

After parsing bus and devnum from `lsusb`, find the sysfs entry that matches:

```
for each entry in /sys/bus/usb/devices/:
    read entry/busnum  (integer, strip whitespace)
    read entry/devnum  (integer, strip whitespace)
    if both match bus and devnum:
        return entry name  →  e.g. "3-1"
```

In Go:

```go
entries, _ := os.ReadDir("/sys/bus/usb/devices")
for _, e := range entries {
    base := "/sys/bus/usb/devices/" + e.Name()
    b, _ := os.ReadFile(base + "/busnum")
    d, _ := os.ReadFile(base + "/devnum")
    if strings.TrimSpace(string(b)) == busStr &&
       strings.TrimSpace(string(d)) == devStr {
        return e.Name() // "3-1"
    }
}
```

This USB path string (e.g. `3-1`) is shown in the "USB Port" column and is
also how ADB reports the physical port, letting you correlate ADB transport
IDs to physical devices.

### 3.2 Reading serial from sysfs (EDL fallback)

For EDL devices where `lsusb -v` fails or returns no serial:

```
/sys/bus/usb/devices/<entry>/serial
```

Read the file directly. No parsing — the content is the raw serial string.

If that file is empty or missing, try:

```
/sys/bus/usb/devices/<entry>/product
```

and search for `SN:([A-Z0-9]+)` in that string.

Last resort: use the sysfs entry name itself (`3-1`) as the identifier. The
device can still be flashed — qdl accepts any unique string via `-S`, and you
can display the port name in the UI instead of a hardware serial.

### 3.3 Pure sysfs EDL scan (most robust method)

You can skip `lsusb` entirely for EDL devices and scan sysfs directly:

```go
entries, _ := os.ReadDir("/sys/bus/usb/devices")
for _, e := range entries {
    base := "/sys/bus/usb/devices/" + e.Name()
    vid, _ := os.ReadFile(base + "/idVendor")
    pid, _ := os.ReadFile(base + "/idProduct")
    if strings.TrimSpace(string(vid)) == "05c6" &&
       strings.TrimSpace(string(pid)) == "9008" {
        serial, _ := os.ReadFile(base + "/serial")
        // use serial, or fall back to product, or entry name
    }
}
```

Advantages over `lsusb -v` / `qdl list` for EDL:
- Works before the USB descriptor is fully enumerable (no race condition)
- No subprocess, no parsing — pure file reads
- sysfs files are world-readable — no root needed for this step

Use sysfs for EDL detection and `lsusb -v` for booted devices (booted devices
always have descriptors ready and lsusb -v gives cleaner serial output).

---

## 4. ADB Integration

ADB is used for two things: reading the build ID from a booted device, and
triggering a reboot into EDL mode.

### 4.1 Listing devices and transport IDs

```
$ adb devices -l
List of devices attached
RF8M11ABCDE        device usb:3-1 transport_id:5
```

Parse each device line with:

```
usb:(\S+).*transport_id:(\d+)
```

This gives you a `usbPath → transportID` map. Since the USB path `3-1` is the
same value resolved from sysfs, you can join them: given a device's sysfs USB
path, look it up here to find its ADB transport ID.

### 4.2 Reading build ID

```
$ adb -t <transport_id> shell getprop ro.build.id
AQ3A.250226.002
```

Use a short timeout (2 seconds). If the device does not respond, leave
build ID empty. It is display-only.

### 4.3 Rebooting to EDL

```
$ adb -t <transport_id> reboot edl
```

Fire and forget — do not wait for output. The device disconnects and
reappears as `05c6:9008` within a few seconds. The scan loop picks it up
automatically on the next tick.

---

## 5. QDL — The Flash Binary

`qdl` is a userspace tool that communicates with a Qualcomm device in EDL mode
via USB using the Sahara and Firehose protocols. You invoke it as a subprocess.

### 5.1 Binary location

Currently hardcoded as `~/aio/qdl/qdl`. In the Go rewrite, make this
configurable via an environment variable (e.g. `QDL_BIN`) with that path
as the default.

### 5.2 Flash command

```
sudo qdl -S <serial> --storage emmc \
    prog_firehose_ddr.elf \
    rawprogram_unsparse0.xml \
    patch0.xml \
    -u 1048576
```

All arguments:

| Argument             | What it does                                                  |
|----------------------|---------------------------------------------------------------|
| `-S <serial>`        | Target a specific device by serial. Required when multiple    |
|                      | EDL devices are connected — without it, qdl picks one        |
|                      | arbitrarily and you will flash the wrong device.              |
| `--storage emmc`     | Specifies the target storage medium. Always `emmc` for these  |
|                      | devices. Other possible values: `ufs`.                        |
| `prog*.elf`          | The Firehose programmer ELF. qdl loads this onto the device   |
|                      | first via the Sahara protocol. Once running on-device, it     |
|                      | handles all subsequent write operations over Firehose.        |
| `rawprogram*.xml`    | Describes which image files to write and to which partition   |
|                      | offsets. qdl reads this to know what to send and where.       |
| `patch*.xml`         | Patch operations applied after writing — typically used to    |
|                      | update partition tables or fixup written data.                |
| `-u 1048576`         | USB read buffer size in bytes (1 MB). Larger = potentially    |
|                      | higher throughput. 1048576 is a safe, tested default.         |

**Critical:** The command must be run with its working directory set to the
firmware directory. All file paths inside `rawprogram*.xml` and `patch*.xml`
are relative. In Go, set `cmd.Dir = firmwareDir` and pass only the basenames
of the three files.

### 5.3 Root requirement

qdl needs root to open `/dev/bus/usb/BUS/DEV`. Two approaches:

**Option A — sudo prefix (current approach):**
```go
cmd := exec.Command("sudo", qdlBin, "-S", serial, "--storage", "emmc", ...)
```
Requires passwordless sudo for the qdl binary in `/etc/sudoers`.

**Option B — run the entire Go binary as root:**
If the app is launched with `sudo ./flasher-gui`, no sudo prefix is needed
for any subprocess. Cleaner for a dedicated flash station machine.

### 5.4 Output and progress parsing

qdl writes all output to stdout and stderr (merge them with
`cmd.Stderr = cmd.Stdout` or `cmd.StderrPipe`). Progress lines look like:

```
flashing partition system ... 45.23%
```

Parse with:

```
(\d+\.?\d*)%
```

Capture the number, convert to int, clamp to 0–100, update the progress bar.
Display the last non-empty line in the log column of the device row.

### 5.5 Exit codes

- `0` — all partitions written and patched successfully
- non-zero — something failed; the last few output lines contain the reason

### 5.6 Parallel flashing

Multiple devices can be flashed simultaneously. Each qdl process targets one
device via `-S <serial>`, so they do not interfere. Spawn one goroutine per
device. Each goroutine owns one `exec.Cmd`, reads its output, and sends
progress updates to the UI via a channel.

```go
type FlashUpdate struct {
    Serial   string
    Progress int    // 0–100
    LastLine string
    Done     bool
    Success  bool
}
```

---

## 6. Firmware Files

### 6.1 Required files

Three files must be present in the firmware directory:

| Pattern           | Role                                         |
|-------------------|----------------------------------------------|
| `prog*.elf`       | Firehose programmer, loaded via Sahara first |
| `rawprogram*.xml` | Partition write instructions                 |
| `patch*.xml`      | Post-write patch operations                  |

Exact filenames vary per build. Detect them by scanning the directory:
- Any `.elf` file whose name contains `prog`
- Any `.xml` file whose name contains `rawprogram`
- Any `.xml` file whose name contains `patch`

A directory is "valid firmware" if it has at least one `.elf` and one
`rawprogram*.xml`. The patch file is required to actually flash.

### 6.2 Firmware directory discovery

The app reads the `FW_PATH` environment variable. If set and pointing to a
directory, it scans for subdirectories that contain valid firmware and shows
them in a dropdown. The user can also browse manually.

In Go:
```go
base := os.Getenv("FW_PATH")
entries, _ := os.ReadDir(base)
for _, e := range entries {
    if e.IsDir() && isValidFirmware(filepath.Join(base, e.Name())) {
        // add to dropdown
    }
}
```

---

## 7. Application State Machine

Each device in the table has a status that controls what is shown and enabled.

```
[disconnected]
      │
      │ appears in USB scan
      ▼
 USER BOOTED ──── ADB on ──── "EDL" button visible
 DEBUG BOOTED ─── ADB on ──── "EDL" button visible
      │
      │ adb -t N reboot edl
      ▼
    EDL ──────────────────── checkbox enabled, "Flash" button enabled
      │
      │ user clicks Flash / Flash Selected
      ▼
  FLASHING ──── progress bar updates from qdl stdout
      │
      ├── exit 0  ──► SUCCESS  (green, progress 100%)
      └── exit !=0 ─► FAILED   (red, progress reset)
      │
      │ device reboots after flash, disconnects, reappears
      ▼
 USER BOOTED (picked up by next scan tick)
```

Rules:
- Only EDL devices can be selected (checkbox enabled only when status == EDL).
- If a non-EDL device's checkbox is clicked, show a dialog offering to reboot
  it to EDL via ADB.
- While any device is flashing, disable the header controls (firmware picker,
  Flash Selected, Reboot All buttons).
- After flash completes, keep the row until the device physically disconnects.
- When a device leaves EDL mode (reboots), silently uncheck it.

---

## 8. Scan Loop in Go

The scan runs in a background goroutine and communicates with the UI via a
channel. Never touch UI widgets from a background goroutine.

```go
func scanLoop(ctx context.Context, updates chan<- ScanResult) {
    ticker := time.NewTicker(1500 * time.Millisecond)
    defer ticker.Stop()
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            result := scanAll() // returns map[serial]DeviceInfo
            updates <- result
        }
    }
}
```

The UI goroutine reads from `updates`, diffs against the current device map,
and adds/updates/removes rows accordingly.

---

## 9. Permissions and udev

| Operation              | Needs root | Notes                              |
|------------------------|------------|------------------------------------|
| `lsusb`                | No         | world-readable                     |
| `lsusb -v -s BUS:DEV`  | Yes        | must open USB device node          |
| sysfs reads            | No         | world-readable                     |
| `adb devices -l`       | No         | adb daemon runs as user            |
| `adb -t N reboot edl`  | No         | adb daemon runs as user            |
| `adb shell getprop`    | No         | adb daemon runs as user            |
| `qdl ...`              | Yes        | must open USB device node          |

The cleanest production setup is a udev rule that grants the flash station
user access to the relevant devices — no runtime sudo needed at all:

```
# /etc/udev/rules.d/99-qdl.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0660", GROUP="plugdev"
```

Reload with `sudo udevadm control --reload && sudo udevadm trigger`.

Alternatively, run the entire Go binary with sudo on the flash station host
and skip the udev setup.

---

## 10. Go Data Structures

```go
type DeviceMode string

const (
    ModeEDL   DeviceMode = "EDL"
    ModeUser  DeviceMode = "USER BOOTED"
    ModeDebug DeviceMode = "DEBUG BOOTED"
)

type DeviceInfo struct {
    Serial       string
    Mode         DeviceMode
    USBPath      string // e.g. "3-1" — physical port identifier
    HasADB       bool
    ADBTransport string // numeric transport ID from adb devices -l
    BuildID      string // ro.build.id, display only
}

type DeviceState struct {
    Info       DeviceInfo
    IsFlashing bool
    Progress   int    // 0–100
    LastLog    string
    Status     string // "edl", "user", "debug", "flashing", "success", "failed"
}

// Top-level device map, keyed by serial
type DeviceMap map[string]*DeviceState
```

---

## 11. Go GUI Toolkit

The Python app uses PyQt6. Equivalent options for Go:

| Toolkit                        | Notes                                                      |
|--------------------------------|------------------------------------------------------------|
| `fyne.io/fyne/v2`              | Pure Go, no CGo, cross-platform. Simpler widget set.       |
|                                | Good fit: table, progress bar, button, dropdown all exist. |
| `github.com/therecipe/qt`      | Full Qt bindings, CGo required, Qt must be installed.      |
|                                | Maximum UI parity with the current PyQt6 app.              |
| `github.com/wailsapp/wails`    | Go backend + HTML/CSS/JS frontend. Fast UI iteration.      |

For a Linux-only flash station, **Fyne** is the simplest path to a working
binary with no external dependencies. If you need pixel-perfect Qt parity,
use the Qt bindings.

---

## 12. Subprocess Pattern for qdl in Go

```go
func flashDevice(
    ctx context.Context,
    serial, firmwareDir, qdlBin string,
    prog, raw, patch string,
    updates chan<- FlashUpdate,
) error {
    cmd := exec.CommandContext(ctx,
        "sudo", qdlBin,
        "-S", serial,
        "--storage", "emmc",
        filepath.Base(prog),
        filepath.Base(raw),
        filepath.Base(patch),
        "-u", "1048576",
    )
    cmd.Dir = firmwareDir
    cmd.Stderr = cmd.Stdout // merge stderr into stdout

    pipe, err := cmd.StdoutPipe()
    if err != nil {
        return err
    }
    if err := cmd.Start(); err != nil {
        return err
    }

    re := regexp.MustCompile(`(\d+\.?\d*)%`)
    scanner := bufio.NewScanner(pipe)
    for scanner.Scan() {
        line := scanner.Text()
        update := FlashUpdate{Serial: serial, LastLine: line}
        if m := re.FindStringSubmatch(line); m != nil {
            pct, _ := strconv.ParseFloat(m[1], 64)
            update.Progress = min(int(pct), 100)
        }
        updates <- update
    }

    err = cmd.Wait()
    updates <- FlashUpdate{
        Serial:  serial,
        Done:    true,
        Success: err == nil,
    }
    return err
}
```

Launch one goroutine per device. All goroutines share the same `updates`
channel. The UI goroutine reads from it and routes each update to the correct
device row by `Serial`.
