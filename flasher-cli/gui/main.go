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
	selected map[string]bool // keyed by USBPath
	running  bool
}

// deviceRow holds stable widget instances for one device — created once, never recycled.
type deviceRow struct {
	check  *widget.Check
	mode   *widget.Label
	path   *widget.Label
	build  *widget.Label
	reboot *widget.Button
	row    *fyne.Container
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

	// ── Progress section ──────────────────────────────────────────

	progressBody := container.NewVBox()
	progressCard := widget.NewCard("Flash Progress", "", container.NewVScroll(progressBody))
	progressCard.Hide()

	// ── Action buttons (declared early; wired to logic below) ─────

	flashSelBtn := widget.NewButton("Flash Selected", nil)
	flashSelBtn.Importance = widget.HighImportance

	flashAllBtn := widget.NewButton("Flash All EDL", nil)

	rebootSelBtn := widget.NewButton("Reboot Selected → EDL", nil)

	rebootFlashBtn := widget.NewButton("Reboot & Flash", nil)
	rebootFlashBtn.Importance = widget.WarningImportance

	selectAllBtn := widget.NewButton("Select All", nil)
	deselectAllBtn := widget.NewButton("Deselect All", nil)

	allActionBtns := []*widget.Button{
		flashSelBtn, flashAllBtn, rebootSelBtn, rebootFlashBtn, selectAllBtn, deselectAllBtn,
	}

	setRunning := func(r bool) {
		st.mu.Lock()
		st.running = r
		st.mu.Unlock()
		fyne.Do(func() {
			for _, b := range allActionBtns {
				if r {
					b.Disable()
				} else {
					b.Enable()
				}
			}
		})
	}

	// ── Flash logic ───────────────────────────────────────────────

	startFlash := func(serials []string) {
		if len(serials) == 0 {
			dialog.ShowInformation("Nothing to flash", "No EDL devices to flash.", w)
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

		setRunning(true)

		type pRow struct {
			bar    *widget.ProgressBar
			pct    *widget.Label
			status *widget.Label
		}
		pRows := make(map[string]*pRow, len(serials))

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
				u := u
				pr, ok := pRows[u.Serial]
				if !ok {
					continue
				}
				fyne.Do(func() {
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
				})
			}
			setRunning(false)
		}()
	}

	// ── Device list ───────────────────────────────────────────────

	rowMap := make(map[string]*deviceRow)
	listScroll := container.NewVScroll(container.NewVBox())
	countLabel := widget.NewLabel("0 devices")

	refreshListUI := func(devs []device.Info) {
		// Remove rows for gone devices.
		active := make(map[string]bool, len(devs))
		for _, d := range devs {
			active[d.USBPath] = true
		}
		for key := range rowMap {
			if !active[key] {
				delete(rowMap, key)
				st.mu.Lock()
				delete(st.selected, key)
				st.mu.Unlock()
			}
		}

		// Build ordered rows.
		rows := make([]fyne.CanvasObject, 0, len(devs))
		for _, d := range devs {
			d := d
			key := d.USBPath
			r, exists := rowMap[key]
			if !exists {
				check := widget.NewCheck("", func(v bool) {
					st.mu.Lock()
					st.selected[key] = v
					st.mu.Unlock()
				})
				modeLbl := widget.NewLabel(string(d.Mode))
				pathLbl := widget.NewLabel(d.USBPath)
				buildLbl := widget.NewLabel(buildIDText(d.BuildID))
				rebootBtn := widget.NewButton("→ EDL", nil)

				r = &deviceRow{
					check:  check,
					mode:   modeLbl,
					path:   pathLbl,
					build:  buildLbl,
					reboot: rebootBtn,
					row: container.NewGridWithColumns(6,
						check,
						widget.NewLabel(d.Serial),
						modeLbl,
						pathLbl,
						buildLbl,
						rebootBtn,
					),
				}
				rowMap[key] = r
			} else {
				r.mode.SetText(string(d.Mode))
				r.path.SetText(d.USBPath)
				r.build.SetText(buildIDText(d.BuildID))
			}

			transport := d.ADBTransport
			if d.HasADB && d.Mode != device.ModeEDL {
				r.reboot.Enable()
				r.reboot.OnTapped = func() { go adb.RebootEDL(transport) }
			} else {
				r.reboot.Disable()
			}

			rows = append(rows, r.row)
		}

		// Replace scroll content entirely so Fyne re-layouts from scratch.
		listScroll.Content = container.NewVBox(rows...)
		listScroll.Refresh()
		countLabel.SetText(fmt.Sprintf("%d device(s)", len(devs)))
	}

	colHeader := container.NewGridWithColumns(6,
		widget.NewLabel(""),
		widget.NewLabelWithStyle("SERIAL", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("MODE", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("USB PATH", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabelWithStyle("BUILD ID", fyne.TextAlignLeading, fyne.TextStyle{Bold: true}),
		widget.NewLabel(""),
	)

	// ── Wire up action buttons ────────────────────────────────────

	selectAllBtn.OnTapped = func() {
		st.mu.Lock()
		for _, d := range st.devices {
			st.selected[d.USBPath] = true
		}
		st.mu.Unlock()
		// Sync checkboxes
		for key, r := range rowMap {
			_ = key
			r.check.SetChecked(true)
		}
	}

	deselectAllBtn.OnTapped = func() {
		st.mu.Lock()
		for k := range st.selected {
			st.selected[k] = false
		}
		st.mu.Unlock()
		for _, r := range rowMap {
			r.check.SetChecked(false)
		}
	}

	flashSelBtn.OnTapped = func() {
		st.mu.Lock()
		var serials []string
		for _, d := range st.devices {
			if st.selected[d.USBPath] && d.Mode == device.ModeEDL {
				serials = append(serials, d.Serial)
			}
		}
		st.mu.Unlock()
		startFlash(serials)
	}

	flashAllBtn.OnTapped = func() {
		st.mu.Lock()
		var serials []string
		for _, d := range st.devices {
			if d.Mode == device.ModeEDL {
				serials = append(serials, d.Serial)
			}
		}
		st.mu.Unlock()
		startFlash(serials)
	}

	rebootSelBtn.OnTapped = func() {
		st.mu.Lock()
		var transports []string
		for _, d := range st.devices {
			if st.selected[d.USBPath] && d.HasADB && d.Mode != device.ModeEDL {
				transports = append(transports, d.ADBTransport)
			}
		}
		st.mu.Unlock()
		if len(transports) == 0 {
			dialog.ShowInformation("Nothing to reboot", "No selected booted devices with ADB.", w)
			return
		}
		for _, t := range transports {
			go adb.RebootEDL(t)
		}
	}

	rebootFlashBtn.OnTapped = func() {
		st.mu.Lock()
		type bootedDev struct {
			usbPath   string
			transport string
		}
		var targets []bootedDev
		for _, d := range st.devices {
			if st.selected[d.USBPath] && d.HasADB && d.Mode != device.ModeEDL {
				targets = append(targets, bootedDev{d.USBPath, d.ADBTransport})
			}
		}
		st.mu.Unlock()

		if len(targets) == 0 {
			dialog.ShowInformation("Nothing to do", "No selected booted devices with ADB.", w)
			return
		}

		setRunning(true)

		go func() {
			// Step 1: reboot all to EDL.
			for _, t := range targets {
				adb.RebootEDL(t.transport)
			}

			// Step 2: wait up to 30s for them to reappear as EDL.
			paths := make(map[string]bool, len(targets))
			for _, t := range targets {
				paths[t.usbPath] = true
			}

			deadline := time.Now().Add(30 * time.Second)
			var edlSerials []string
			for time.Now().Before(deadline) {
				time.Sleep(500 * time.Millisecond)
				devs, _ := usb.Scan()
				edlSerials = nil
				for _, d := range devs {
					if d.Mode == device.ModeEDL && paths[d.USBPath] {
						edlSerials = append(edlSerials, d.Serial)
					}
				}
				if len(edlSerials) == len(targets) {
					break
				}
			}

			if len(edlSerials) == 0 {
				fyne.Do(func() {
					dialog.ShowError(fmt.Errorf("devices did not appear in EDL within 30s"), w)
				})
				setRunning(false)
				return
			}

			// Step 3: flash.
			startFlash(edlSerials)
		}()
	}

	deviceCard := widget.NewCard("Devices", "", container.NewBorder(
		container.NewVBox(colHeader, widget.NewSeparator()),
		container.NewVBox(
			widget.NewSeparator(),
			container.NewHBox(selectAllBtn, deselectAllBtn, countLabel),
			container.NewHBox(rebootSelBtn, flashSelBtn, flashAllBtn, rebootFlashBtn),
		),
		nil, nil,
		listScroll,
	))

	// ── Auto-refresh goroutine ────────────────────────────────────

	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for range ticker.C {
			st.mu.Lock()
			isRunning := st.running
			st.mu.Unlock()
			if isRunning {
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

			fyne.Do(func() {
				refreshListUI(devs)
			})
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

func buildIDText(id string) string {
	if id == "" {
		return "—"
	}
	return id
}
