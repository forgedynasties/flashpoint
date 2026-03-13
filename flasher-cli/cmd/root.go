// Package cmd contains all CLI subcommands.
package cmd

import (
	"os"

	"github.com/spf13/cobra"
)

var rootCmd = &cobra.Command{
	Use:   "flasher",
	Short: "Qualcomm flash station CLI",
	Long: `flasher — list and flash Qualcomm devices via EDL / qdl.

Environment variables:
  QDL_BIN      path to the qdl binary (default: ~/aio/qdl/qdl)
  FW_PATH      firmware base directory used by --all and the default path
`,
}

// Execute is the entry point called from main.
func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
