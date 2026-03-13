package device

// Mode represents which USB personality a device is presenting.
type Mode string

const (
	ModeEDL   Mode = "EDL"
	ModeUser  Mode = "USER BOOTED"
	ModeDebug Mode = "DEBUG BOOTED"
)

// KnownIDs maps VID:PID strings to their Mode.
var KnownIDs = map[string]Mode{
	"05c6:9008": ModeEDL,
	"18d1:4ee1": ModeUser,
	"18d1:4e11": ModeDebug,
	"05c6:901f": ModeDebug,
}

// Info is the raw data resolved from USB / sysfs / ADB for one device.
type Info struct {
	Serial       string // hardware serial (_SN:... or sysfs fallback)
	Mode         Mode
	USBPath      string // sysfs topology path, e.g. "3-1"
	VidPid       string // e.g. "05c6:9008"
	HasADB       bool
	ADBTransport string // numeric ID from "adb devices -l"
	BuildID      string // ro.build.id, display only
}
