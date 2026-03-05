### 1. Set Global Permissions (No Group)

Create (or overwrite) the udev rule file:

```bash
sudo nano /etc/udev/rules.d/99-qualcomm.rules

```

Paste this exact line. The `MODE="0666"` is the "Magic Key" here—it gives read/write permissions to **everyone** globally:

```udev
SUBSYSTEM=="usb", ATTR{idVendor}=="05c6", ATTR{idProduct}=="9008", MODE="0666"

```

### 2. Force Arch to Apply the Rule

Run these to refresh the USB stack:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger

```

**Important:** Physically unplug the device and plug it back in now.

---

### 3. Verify Without Sudo

Test it in your terminal as a normal user:

```bash
~/aio/qdl/qdl list

```

If you see the serial number and **not** an "Unable to open" error, the GUI will now work perfectly.

---