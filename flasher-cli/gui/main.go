package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"fyne.io/fyne/v2"
	"fyne.io/fyne/v2/app"
	"fyne.io/fyne/v2/container"
	"fyne.io/fyne/v2/dialog"
	"fyne.io/fyne/v2/theme"
	"fyne.io/fyne/v2/widget"

	"github.com/cd4li/flasher-cli/internal/adb"
	"github.com/cd4li/flasher-cli/internal/device"
	"github.com/cd4li/flasher-cli/internal/flash"
	"github.com/cd4li/flasher-cli/internal/firmware"
	"github.com/cd4li/flasher-cli/internal/usb"
)

type appState struct {
	mu       sync.Mutex
	devices  []device.Info
	selected map[string]bool
	flashing bool
}

func main() {
	a := app.New()
	a.Settings().SetTheme(theme.LightTheme())

	w := a.NewWindow("2Flasher")
	w.Resize(fyne.NewSize(980, 700))

	st := &appState{selected: make(map[string]bool)}

	// ── Config ────────────────────────────────────────────────────

	home, _ := os.UserHomeDir()

	fwEntry := widget.NewEntry()
	fwEntry.SetPlaceHolder("path to firmware directory")
	if v := os.Getenv("FW_PATH"); v != "" {
		fwEntry.SetText(v)
	}

	qdlEntry := widget.NewEntry()
	if v := os.Getenv("QDL_BIN"); v != "" {
		qdlEntry.SetText(v)
	} else {
		qdlEntry.SetText(filepath.Join(home, "aio", "qdl", "qdl"))
	}

	fwBrowseBtn := widget.NewButton("Browse", func() {
		dialog.ShowFolderOpen(func(u fyne.ListableURI, err error) {
			if err == nil && u != nil {
				fwEntry.SetText(u.Path())
			}
		}, w)
	})

	qdlBrowseBtn := widget.NewButton("Browse", func() {
		dialog.ShowFileOpen(func(u fyne.URIReadCloser, err error) {
			if err == nil && u != nil {
				u.Close()
				qdlEntry.SetText(u.URI().Path())
			}
		}, w)
	})

	configCard := widget.NewCard("Configuration", "", container.NewVBox(
		container.NewBorder(nil, nil,
			widget.NewLabelWithStyle("Firmware Dir", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
			fwBrowseBtn, fwEntry,
		),
		container.NewBorder(nil, nil,
			widget.NewLabelWithStyle("QDL Binary  ", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
			qdlBrowseBtn, qdlEntry,
		),
	))

	// ── Progress section (declared early for use in startFlash) ───

	progressBody := container.NewVBox()
	progressCard := widget.NewCard("Flash Progress", "", container.NewVScroll(progressBody))
	progressCard.Hide()

	// ── Flash logic ───────────────────────────────────────────────

	startFlash := func(serials []string) {
		if len(serials) == 0 {
			dialog.ShowInformation("Nothing to flash", "No EDL devices selected.", w)
			return
		}
		fwDir := fwEntry.Text
		if fwDir == "" {
			dialog.ShowError(fmt.Errorf("set a firmware directory first"), w)
			return
		}
		os.Setenv("QDL_BIN", qdlEntry.Text)

		fw, err := firmware.Resolve(fwDir)
		if err != nil {
			dialog.ShowError(fmt.Errorf("firmware: %w", err), w)
			return
		}

		st.mu.Lock()
		st.flashing = true
		st.mu.Unlock()

		type pRow struct {
			bar    *widget.ProgressBar
			pct    *widget.Label
			status *widget.Label
		}
		pRows := make(map[string]*pRow, len(serials))

		// Reset progress UI
		progressBody.Objects = nil
		for _, s := range serials {
			bar := widget.NewProgressBar()
			bar.Min, bar.Max = 0, 100
			pct := widget.NewLabel("  0%")
			status := widget.NewLabel("in progress…")
			row := container.NewBorder(nil, nil,
				widget.NewLabelWithStyle(s, fyne.TextAlignLeading, fyne.TextStyle{Bold: true, Monospace: true}),
				container.NewHBox(pct, status),
				bar,
			)
			pRows[s] = &pRow{bar, pct, status}
			progressBody.Add(row)
		}
		progressBody.Refresh()
		progressCard.Show()

		ctx := context.Background()
		updates := flash.Many(ctx, serials, fw, false)

		go func() {
			for u := range updates {
				pr, ok := pRows[u.Serial]
				if !ok {
					continue
				}
				pr.bar.SetValue(float64(u.Progress))
				pr.pct.SetText(fmt.Sprintf("%3d%%", u.Progress))
				if u.Done {
					if u.Success {
						pr.status.SetText("✓ done")
					} else {
						msg := "✗ failed"
						if u.Err != nil {
							msg = "✗ " + u.Err.Error()
						}
						pr.status.SetText(msg)
					}
				}
			}
			st.mu.Lock()
			st.flashing = false
			st.mu.Unlock()
		}()
	}

	// ── Device list ───────────────────────────────────────────────

	colHeader := container.NewGridWithColumns(6,
		widget.NewLabel(""),
		widget.NewLabelWithStyle("SERIAL", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("MODE", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("USB PATH", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("BUILD ID", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabel(""),
	)

	deviceList := widget.NewList(
		func() int {
			st.mu.Lock()
			defer st.mu.Unlock()
			return len(st.devices)
		},
		func() fyne.CanvasObject {
			return container.NewGridWithColumns(6,
				widget.NewCheck("", nil),
				widget.NewLabel(""),
				widget.NewLabel(""),
				widget.NewLabel(""),
				widget.NewLabel(""),
				widget.NewButton("→ EDL", nil),
			)
		},
		func(id widget.ListItemID, obj fyne.CanvasObject) {
			st.mu.Lock()
			if id >= len(st.devices) {
				st.mu.Unlock()
				return
			}
			d := st.devices[id]
			checked := st.selected[d.Serial]
			st.mu.Unlock()

			row := obj.(*fyne.Container)
			check := row.Objects[0].(*widget.Check)
			serialLbl := row.Objects[1].(*widget.Label)
			modeLbl := row.Objects[2].(*widget.Label)
			pathLbl := row.Objects[3].(*widget.Label)
			buildLbl := row.Objects[4].(*widget.Label)
			rebootBtn := row.Objects[5].(*widget.Button)

			serial := d.Serial
			check.Checked = checked
			check.OnChanged = func(v bool) {
				st.mu.Lock()
				st.selected[serial] = v
				st.mu.Unlock()
			}
			check.Refresh()

			serialLbl.SetText(d.Serial)
			modeLbl.SetText(string(d.Mode))
			pathLbl.SetText(d.USBPath)
			buildID := d.BuildID
			if buildID == "" {
				buildID = "—"
			}
			buildLbl.SetText(buildID)

			transport := d.ADBTransport
			if d.HasADB && d.Mode != device.ModeEDL {
				rebootBtn.Enable()
				rebootBtn.OnTapped = func() { go adb.RebootEDL(transport) }
			} else {
				rebootBtn.Disable()
			}
		},
	)
	// Suppress Fyne's built-in row selection highlight
	deviceList.OnUnselected = func(widget.ListItemID) {}

	// ── Flash buttons ─────────────────────────────────────────────

	flashSelBtn := widget.NewButton("Flash Selected", func() {
		st.mu.Lock()
		var serials []string
		for _, d := range st.devices {
			if st.selected[d.Serial] && d.Mode == device.ModeEDL {
				serials = append(serials, d.Serial)
			}
		}
		st.mu.Unlock()
		startFlash(serials)
	})
	flashSelBtn.Importance = widget.HighImportance

	flashAllBtn := widget.NewButton("Flash All EDL", func() {
		st.mu.Lock()
		var serials []string
		for _, d := range st.devices {
			if d.Mode == device.ModeEDL {
				serials = append(serials, d.Serial)
			}
		}
		st.mu.Unlock()
		startFlash(serials)
	})

	deviceCard := widget.NewCard("Devices", "", container.NewBorder(
		container.NewVBox(colHeader, widget.NewSeparator()),
		container.NewVBox(widget.NewSeparator(), container.NewHBox(flashSelBtn, flashAllBtn)),
		nil, nil,
		deviceList,
	))

	// ── Auto-refresh goroutine ────────────────────────────────────

	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			st.mu.Lock()
			isFlashing := st.flashing
			st.mu.Unlock()
			if isFlashing {
				continue
			}

			devs, _ := usb.Scan()
			transports, _ := adb.ListTransports()
			for i := range devs {
				if t, ok := transports[devs[i].USBPath]; ok {
					devs[i].HasADB = true
					devs[i].ADBTransport = t
					devs[i].BuildID = adb.BuildID(t)
				}
			}

			st.mu.Lock()
			st.devices = devs
			st.mu.Unlock()
			deviceList.Refresh()
		}
	}()

	// ── Window layout ─────────────────────────────────────────────

	w.SetContent(container.NewBorder(
		configCard,
		progressCard,
		nil, nil,
		deviceCard,
	))
	w.ShowAndRun()
}
