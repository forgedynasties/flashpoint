package cmd

import (
	"fmt"
	"os"
	"text/tabwriter"

	"github.com/cd4li/flasher-cli/internal/adb"
	"github.com/cd4li/flasher-cli/internal/device"
	"github.com/cd4li/flasher-cli/internal/usb"
	"github.com/spf13/cobra"
)

var listCmd = &cobra.Command{
	Use:   "list",
	Short: "List all connected Qualcomm devices and their modes",
	RunE:  runList,
}

var flagNoADB bool

func init() {
	listCmd.Flags().BoolVar(&flagNoADB, "no-adb", false, "skip ADB enrichment (build ID / transport ID)")
	rootCmd.AddCommand(listCmd)
}

func runList(_ *cobra.Command, _ []string) error {
	devices, err := usb.Scan()
	if err != nil {
		return fmt.Errorf("USB scan: %w", err)
	}

	if len(devices) == 0 {
		fmt.Fprintln(os.Stderr, "No Qualcomm devices found.")
		return nil
	}

	// Enrich booted devices with ADB info unless suppressed.
	if !flagNoADB {
		transports, _ := adb.ListTransports() // best-effort
		for i := range devices {
			d := &devices[i]
			if d.Mode == device.ModeEDL {
				continue
			}
			if transports == nil {
				continue
			}
			tid, ok := transports[d.USBPath]
			if !ok {
				continue
			}
			d.HasADB = true
			d.ADBTransport = tid
			d.BuildID = adb.BuildID(tid)
		}
	}

	printTable(devices)
	return nil
}

func printTable(devices []device.Info) {
	w := tabwriter.NewWriter(os.Stdout, 0, 0, 2, ' ', 0)
	fmt.Fprintln(w, "SERIAL\tMODE\tUSB PATH\tVID:PID\tADB TRANSPORT\tBUILD ID")
	fmt.Fprintln(w, "------\t----\t--------\t-------\t-------------\t--------")
	for _, d := range devices {
		transport := d.ADBTransport
		if transport == "" {
			transport = "-"
		}
		buildID := d.BuildID
		if buildID == "" {
			buildID = "-"
		}
		fmt.Fprintf(w, "%s\t%s\t%s\t%s\t%s\t%s\n",
			d.Serial, d.Mode, d.USBPath, d.VidPid, transport, buildID)
	}
	w.Flush()
}
