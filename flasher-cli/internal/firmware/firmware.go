// Package firmware locates and validates firmware directories for qdl.
package firmware

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Files holds the three required files for a qdl flash operation.
type Files struct {
	Dir      string // absolute directory path (qdl runs with this as CWD)
	Prog     string // basename of prog*.elf
	RawProgram string // basename of rawprogram*.xml
	Patch    string // basename of patch*.xml
}

// Resolve finds the qdl firmware files inside dir.
// Returns an error if any required file is missing.
func Resolve(dir string) (*Files, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("read firmware dir %q: %w", dir, err)
	}

	f := &Files{Dir: dir}
	for _, e := range entries {
		name := e.Name()
		lower := strings.ToLower(name)
		switch {
		case strings.Contains(lower, "prog") && strings.HasSuffix(lower, ".elf"):
			f.Prog = name
		case strings.Contains(lower, "rawprogram") && strings.HasSuffix(lower, ".xml"):
			f.RawProgram = name
		case strings.Contains(lower, "patch") && strings.HasSuffix(lower, ".xml"):
			f.Patch = name
		}
	}

	if f.Prog == "" {
		return nil, fmt.Errorf("no prog*.elf found in %s", dir)
	}
	if f.RawProgram == "" {
		return nil, fmt.Errorf("no rawprogram*.xml found in %s", dir)
	}
	if f.Patch == "" {
		return nil, fmt.Errorf("no patch*.xml found in %s", dir)
	}
	return f, nil
}

// Discover scans base for subdirectories that contain valid firmware.
// base defaults to the FW_PATH env variable if empty.
func Discover(base string) ([]string, error) {
	if base == "" {
		base = os.Getenv("FW_PATH")
	}
	if base == "" {
		return nil, fmt.Errorf("no firmware base path (set FW_PATH or pass --firmware-dir)")
	}

	entries, err := os.ReadDir(base)
	if err != nil {
		return nil, fmt.Errorf("read %q: %w", base, err)
	}

	var dirs []string
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		candidate := filepath.Join(base, e.Name())
		if _, err := Resolve(candidate); err == nil {
			dirs = append(dirs, candidate)
		}
	}
	return dirs, nil
}
