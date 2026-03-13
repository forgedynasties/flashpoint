// Package flash manages qdl subprocess execution and progress streaming.
package flash

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"

	"github.com/cd4li/flasher-cli/internal/firmware"
)

var progressRe = regexp.MustCompile(`(\d+\.?\d*)%`)

// Update is a progress message from a running flash operation.
type Update struct {
	Serial   string
	Progress int    // 0–100
	LastLine string
	Done     bool
	Success  bool
	Err      error
}

// qdlBin returns the path to the qdl binary.
// Reads QDL_BIN env var, falls back to ~/aio/qdl/qdl.
func qdlBin() string {
	if v := os.Getenv("QDL_BIN"); v != "" {
		return v
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, "aio", "qdl", "qdl")
}

// Device flashes a single device identified by serial using the provided firmware.
// Progress updates are sent to the updates channel. The channel is NOT closed by
// this function — the caller decides the channel lifetime.
// If dryRun is true, qdl is invoked with -n (parse and validate without writing).
func Device(ctx context.Context, serial string, fw *firmware.Files, dryRun bool, updates chan<- Update) {
	bin := qdlBin()

	args := []string{
		bin,
		"-S", serial,
		"--storage", "emmc",
		fw.Prog,
		fw.RawProgram,
		fw.Patch,
		"-u", "1048576",
	}
	if dryRun {
		args = append(args, "-n")
	}

	cmd := exec.CommandContext(ctx, "sudo", args...)
	cmd.Dir = fw.Dir
	// Merge stderr into stdout so we capture everything.
	pipe, err := cmd.StdoutPipe()
	if err != nil {
		updates <- Update{Serial: serial, Done: true, Err: fmt.Errorf("stdout pipe: %w", err)}
		return
	}
	cmd.Stderr = cmd.Stdout

	if err := cmd.Start(); err != nil {
		updates <- Update{Serial: serial, Done: true, Err: fmt.Errorf("start qdl: %w", err)}
		return
	}

	scanner := bufio.NewScanner(pipe)
	var lastLine string
	for scanner.Scan() {
		line := scanner.Text()
		if line != "" {
			lastLine = line
		}
		u := Update{Serial: serial, LastLine: line}
		if m := progressRe.FindStringSubmatch(line); m != nil {
			pct, _ := strconv.ParseFloat(m[1], 64)
			if pct > 100 {
				pct = 100
			}
			u.Progress = int(pct)
		}
		updates <- u
	}

	waitErr := cmd.Wait()
	updates <- Update{
		Serial:   serial,
		Progress: func() int {
			if waitErr == nil {
				return 100
			}
			return 0
		}(),
		LastLine: lastLine,
		Done:     true,
		Success:  waitErr == nil,
		Err:      waitErr,
	}
}

// Many flashes multiple devices in parallel, one goroutine each.
// It returns a single channel on which all updates arrive; it is closed when
// every flash goroutine finishes.
func Many(ctx context.Context, serials []string, fw *firmware.Files, dryRun bool) <-chan Update {
	ch := make(chan Update, len(serials)*4)
	go func() {
		done := make(chan struct{}, len(serials))
		for _, s := range serials {
			s := s
			go func() {
				Device(ctx, s, fw, dryRun, ch)
				done <- struct{}{}
			}()
		}
		for range serials {
			<-done
		}
		close(ch)
	}()
	return ch
}
