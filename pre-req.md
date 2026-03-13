## Dependencies

### GUI

```bash
sudo apt install libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
libxcb-xkb1 libx11-xcb1
```

### QDL

```bash
sudo apt install libxml2-dev libusb-1.0-0-dev help2man
make
```

---

### 1. Set Global Permissions (No Group)

Create (or overwrite) the udev rule file:

```bash
sudo nano /etc/udev/rules.d/99-qualcomm.rules

```

Paste this exact line. The `MODE="0666"` is the "Magic Key" here—it gives read/write permissions to **everyone** globally:

```udev
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666"

```

### 2. Force Arch to Apply the Rule

Run these to refresh the USB stack:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger

```

**Important:** Physically unplug the device and plug it back in now.

---

### 3. Passwordless sudo for QDL

The app runs `qdl` via `sudo` and requires a NOPASSWD rule so it never prompts
for a password mid-flash. Create the sudoers drop-in:

```bash
sudo visudo -f /etc/sudoers.d/qdl
```

Add this line (replace the username if needed):

```
flasher02 ALL=(ALL) NOPASSWD: /home/flasher02/aio/qdl/qdl
```

Verify it works without a prompt:

```bash
sudo -n /home/flasher02/aio/qdl/qdl --help
```

The app will refuse to start and display this instruction if the rule is missing.

---

### 4. Verify Without Sudo

Test it in your terminal as a normal user:

```bash
.qdl list

```

If you see the serial number and **not** an "Unable to open" error, the GUI will now work perfectly.

---