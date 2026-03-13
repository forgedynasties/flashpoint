package cmd

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/cd4li/flasher-cli/internal/firmware"
	"github.com/cd4li/flasher-cli/internal/flash"
	"github.com/cd4li/flasher-cli/internal/usb"
	"github.com/spf13/cobra"
)

var flashCmd = &cobra.Command{
	Use:   "flash",
	Short: "Flash one or more EDL devices by serial number",
	Long: `Flash one or more EDL devices in parallel using qdl.

Examples:
  # Flash a single device
  flasher flash --serial A1B2C3D4 --firmware-dir /path/to/fw

  # Flash multiple devices at once
  flasher flash --serial A1B2C3D4,E5F6G7H8 --firmware-dir /path/to/fw

  # Let the tool auto-detect all EDL devices and flash them all
  flasher flash --all --firmware-dir /path/to/fw

  # Dry run — parse firmware and validate without writing (qdl -n)
  flasher flash --all --firmware-dir /path/to/fw --dry-run
`,
	RunE: runFlash,
}

var (
	flagSerials     string
	flagFirmwareDir string
	flagFlashAll    bool
	flagDryRun      bool
)

func init() {
	flashCmd.Flags().StringVarP(&flagSerials, "serial", "s", "", "comma-separated serial numbers to flash")
	flashCmd.Flags().StringVarP(&flagFirmwareDir, "firmware-dir", "f", "", "firmware directory (overrides FW_PATH env)")
	flashCmd.Flags().BoolVar(&flagFlashAll, "all", false, "flash all currently connected EDL devices")
	flashCmd.Flags().BoolVarP(&flagDryRun, "dry-run", "n", false, "parse and validate firmware without writing (passes -n to qdl)")
	rootCmd.AddCommand(flashCmd)
}

func runFlash(_ *cobra.Command, _ []string) error {
	if !flagFlashAll && flagSerials == "" {
		return fmt.Errorf("specify --serial <SN[,SN...]> or --all")
	}

	// Resolve firmware
	fwDir := flagFirmwareDir
	if fwDir == "" {
		fwDir = os.Getenv("FW_PATH")
	}
	if fwDir == "" {
		return fmt.Errorf("firmware directory required: use --firmware-dir or set FW_PATH")
	}
	fw, err := firmware.Resolve(fwDir)
	if err != nil {
		return fmt.Errorf("firmware: %w", err)
	}
	fmt.Printf("Firmware: %s\n  ELF: %s\n  RAW: %s\n  PATCH: %s\n\n",
		fw.Dir, fw.Prog, fw.RawProgram, fw.Patch)

	// Resolve target serials
	var serials []string
	if flagFlashAll {
		serials, err = edlSerials()
		if err != nil {
			return err
		}
		if len(serials) == 0 {
			fmt.Fprintln(os.Stderr, "No EDL devices found.")
			return nil
		}
		fmt.Printf("Auto-detected %d EDL device(s): %s\n\n", len(serials), strings.Join(serials, ", "))
	} else {
		for _, s := range strings.Split(flagSerials, ",") {
			s = strings.TrimSpace(s)
			if s != "" {
				serials = append(serials, s)
			}
		}
	}

	// Validate that the requested serials are in EDL mode
	if !flagFlashAll {
		if err := validateEDL(serials); err != nil {
			return err
		}
	}

	verb := "Flashing"
	if flagDryRun {
		verb = "Dry-running"
	}
	fmt.Printf("%s %d device(s): %s\n\n", verb, len(serials), strings.Join(serials, ", "))

	// Handle Ctrl-C gracefully
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	updates := flash.Many(ctx, serials, fw, flagDryRun)

	// Track per-device state for the final summary
	type state struct {
		progress int
		lastLine string
		done     bool
		success  bool
		err      error
	}
	deviceState := make(map[string]*state, len(serials))
	for _, s := range serials {
		deviceState[s] = &state{}
	}

	for u := range updates {
		st := deviceState[u.Serial]
		if u.Progress > st.progress {
			st.progress = u.Progress
		}
		if u.LastLine != "" {
			st.lastLine = u.LastLine
		}
		if u.Done {
			st.done = true
			st.success = u.Success
			st.err = u.Err
			if u.Success {
				fmt.Printf("[%s] DONE ✓\n", u.Serial)
			} else {
				fmt.Printf("[%s] FAILED: %v\n", u.Serial, u.Err)
			}
		} else if u.Progress > 0 {
			fmt.Printf("[%s] %3d%%  %s\n", u.Serial, u.Progress, u.LastLine)
		} else if u.LastLine != "" {
			fmt.Printf("[%s] %s\n", u.Serial, u.LastLine)
		}
	}

	// Final summary
	fmt.Println()
	ok, failed := 0, 0
	for _, s := range serials {
		st := deviceState[s]
		if st.success {
			ok++
		} else {
			failed++
		}
	}
	fmt.Printf("Result: %d succeeded, %d failed\n", ok, failed)
	if failed > 0 {
		return fmt.Errorf("%d device(s) failed to flash", failed)
	}
	return nil
}

// edlSerials returns the serial numbers of all currently EDL-mode devices.
func edlSerials() ([]string, error) {
	devices, err := usb.Scan()
	if err != nil {
		return nil, fmt.Errorf("USB scan: %w", err)
	}
	var out []string
	for _, d := range devices {
		if d.Mode == "EDL" {
			out = append(out, d.Serial)
		}
	}
	return out, nil
}

// validateEDL checks that all requested serials are present and in EDL mode.
func validateEDL(serials []string) error {
	devices, err := usb.Scan()
	if err != nil {
		return fmt.Errorf("USB scan: %w", err)
	}
	edlSet := make(map[string]bool)
	for _, d := range devices {
		if d.Mode == "EDL" {
			edlSet[d.Serial] = true
		}
	}
	var missing []string
	for _, s := range serials {
		if !edlSet[s] {
			missing = append(missing, s)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("device(s) not found in EDL mode: %s\n(use 'flasher list' to see current device states)", strings.Join(missing, ", "))
	}
	return nil
}
