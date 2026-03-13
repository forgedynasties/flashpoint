// Package adb wraps the adb command for device discovery and control.
package adb

import (
	"bufio"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strings"
	"time"
)

var adbTransportRe = regexp.MustCompile(`usb:(\S+).*transport_id:(\d+)`)

// TransportMap maps USB path (e.g. "3-1") → ADB transport ID.
type TransportMap map[string]string

// ListTransports runs "adb devices -l" and returns a USB-path → transport-ID map.
func ListTransports() (TransportMap, error) {
	out, err := runADB("devices", "-l")
	if err != nil {
		return nil, err
	}
	m := make(TransportMap)
	scanner := bufio.NewScanner(strings.NewReader(out))
	for scanner.Scan() {
		matches := adbTransportRe.FindStringSubmatch(scanner.Text())
		if matches == nil {
			continue
		}
		usbPath := matches[1]  // e.g. "3-1"
		transport := matches[2] // e.g. "5"
		m[usbPath] = transport
	}
	return m, nil
}

// BuildID reads ro.build.id from an ADB-connected device identified by transport ID.
// Returns empty string on timeout or error.
func BuildID(transportID string) string {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "adb", "-t", transportID, "shell", "getprop", "ro.build.id")
	out, err := cmd.Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// RebootEDL sends "adb -t <transport> reboot edl" — fire and forget.
func RebootEDL(transportID string) error {
	cmd := exec.Command("adb", "-t", transportID, "reboot", "edl")
	return cmd.Start() // don't Wait — device disconnects immediately
}

func runADB(args ...string) (string, error) {
	cmd := exec.Command("adb", args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("adb %v: %w", args, err)
	}
	return string(out), nil
}
