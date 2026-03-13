// Package usb detects Qualcomm devices via lsusb and sysfs.
package usb

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/cd4li/flasher-cli/internal/device"
)

var (
	lsusbLineRe = regexp.MustCompile(`Bus (\d+) Device (\d+): ID ([\da-f]{4}:[\da-f]{4})`)
	iserialRe   = regexp.MustCompile(`iSerial\s+\d+\s+(\S+)`)
	snRe        = regexp.MustCompile(`_SN:([0-9a-fA-F]+)`)
	snProductRe = regexp.MustCompile(`SN:([A-Z0-9]+)`)
)

// Scan returns all connected Qualcomm devices discovered via lsusb + sysfs.
// It never returns an error — partial results are always returned.
func Scan() ([]device.Info, error) {
	lsusbDevices, err := parseLsusb()
	if err != nil {
		// Fall back to pure sysfs scan
		return sysfsScanAll(), nil
	}

	var result []device.Info
	for _, d := range lsusbDevices {
		// Resolve sysfs path
		usbPath, _ := resolveUSBPath(d.bus, d.devnum)

		var serial string
		// For booted devices, prefer lsusb -v for a clean serial.
		// For EDL, use sysfs directly (no race condition).
		if d.mode == device.ModeEDL {
			serial = sysfsSerial(usbPath)
		} else {
			serial, _ = lsusbVerboseSerial(d.bus, d.devnum)
			if serial == "" {
				serial = sysfsSerial(usbPath)
			}
		}
		if serial == "" {
			serial = usbPath
		}

		result = append(result, device.Info{
			Serial:  serial,
			Mode:    d.mode,
			USBPath: usbPath,
			VidPid:  d.vidpid,
		})
	}
	return result, nil
}

// lsusbEntry is an intermediate struct used only inside this package.
type lsusbEntry struct {
	bus    string
	devnum string
	vidpid string
	mode   device.Mode
}

func parseLsusb() ([]lsusbEntry, error) {
	out, err := runCommand("lsusb")
	if err != nil {
		return nil, fmt.Errorf("lsusb: %w", err)
	}

	var entries []lsusbEntry
	scanner := bufio.NewScanner(strings.NewReader(out))
	for scanner.Scan() {
		line := scanner.Text()
		m := lsusbLineRe.FindStringSubmatch(line)
		if m == nil {
			continue
		}
		vidpid := m[3]
		mode, known := device.KnownIDs[vidpid]
		if !known {
			continue
		}
		entries = append(entries, lsusbEntry{
			bus:    m[1],
			devnum: m[2],
			vidpid: vidpid,
			mode:   mode,
		})
	}

	return entries, nil
}

// lsusbVerboseSerial runs "lsusb -v -s BUS:DEV" and extracts the iSerial value.
func lsusbVerboseSerial(bus, devnum string) (string, error) {
	out, err := runCommandSudo("lsusb", "-v", "-s", fmt.Sprintf("%s:%s", bus, devnum))
	if err != nil {
		return "", err
	}
	if m := iserialRe.FindStringSubmatch(out); m != nil {
		raw := m[1]
		// Strip _SN: prefix if present
		if sm := snRe.FindStringSubmatch(raw); sm != nil {
			return sm[1], nil
		}
		return raw, nil
	}
	return "", nil
}

// resolveUSBPath finds the sysfs entry name (e.g. "3-1") for a given bus+devnum.
func resolveUSBPath(bus, devnum string) (string, error) {
	entries, err := os.ReadDir("/sys/bus/usb/devices")
	if err != nil {
		return "", err
	}
	for _, e := range entries {
		base := filepath.Join("/sys/bus/usb/devices", e.Name())
		b, _ := os.ReadFile(filepath.Join(base, "busnum"))
		d, _ := os.ReadFile(filepath.Join(base, "devnum"))
		bStr := strings.TrimSpace(string(b))
		dStr := strings.TrimSpace(string(d))
		// lsusb pads to 3 digits; sysfs does not — compare as trimmed ints
		if trimLeadingZeros(bStr) == trimLeadingZeros(bus) &&
			trimLeadingZeros(dStr) == trimLeadingZeros(devnum) {
			return e.Name(), nil
		}
	}
	return "", fmt.Errorf("sysfs entry not found for bus=%s dev=%s", bus, devnum)
}

// sysfsSerial reads the serial from /sys/bus/usb/devices/<usbPath>/serial
// and falls back through product → entry name.
func sysfsSerial(usbPath string) string {
	if usbPath == "" {
		return ""
	}
	base := filepath.Join("/sys/bus/usb/devices", usbPath)

	serial, _ := os.ReadFile(filepath.Join(base, "serial"))
	if s := strings.TrimSpace(string(serial)); s != "" {
		if m := snRe.FindStringSubmatch(s); m != nil {
			return m[1]
		}
		return s
	}

	product, _ := os.ReadFile(filepath.Join(base, "product"))
	if m := snProductRe.FindStringSubmatch(string(product)); m != nil {
		return m[1]
	}

	// Last resort: the sysfs path itself ("3-1") is unique per physical port.
	return usbPath
}

// sysfsScanAll scans /sys/bus/usb/devices for known VID:PIDs — no lsusb needed.
func sysfsScanAll() []device.Info {
	entries, err := os.ReadDir("/sys/bus/usb/devices")
	if err != nil {
		return nil
	}

	var result []device.Info
	for _, e := range entries {
		base := filepath.Join("/sys/bus/usb/devices", e.Name())
		vid, _ := os.ReadFile(filepath.Join(base, "idVendor"))
		pid, _ := os.ReadFile(filepath.Join(base, "idProduct"))
		vidpid := strings.TrimSpace(string(vid)) + ":" + strings.TrimSpace(string(pid))

		mode, known := device.KnownIDs[vidpid]
		if !known {
			continue
		}

		serial := sysfsSerial(e.Name())
		if serial == "" {
			serial = e.Name()
		}

		result = append(result, device.Info{
			Serial:  serial,
			Mode:    mode,
			USBPath: e.Name(),
			VidPid:  vidpid,
		})
	}
	return result
}

func trimLeadingZeros(s string) string {
	s = strings.TrimLeft(s, "0")
	if s == "" {
		return "0"
	}
	return s
}
