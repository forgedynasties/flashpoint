package usb

import (
	"fmt"
	"os/exec"
	"strings"
)

// runCommand runs a command and returns combined stdout+stderr.
func runCommand(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return string(out), fmt.Errorf("%s %v: %w", name, args, err)
	}
	return strings.TrimRight(string(out), "\n"), nil
}

// runCommandSudo runs a command under sudo.
func runCommandSudo(name string, args ...string) (string, error) {
	allArgs := append([]string{name}, args...)
	cmd := exec.Command("sudo", allArgs...)
	out, err := cmd.CombinedOutput()
	return string(out), err
}
