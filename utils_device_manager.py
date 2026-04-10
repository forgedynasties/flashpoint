"""Device scanning and detection utilities."""
import logging
import subprocess

log = logging.getLogger(__name__)


class DeviceScanner:

    @staticmethod
    def get_build_id(transport_id):
        """Get build ID from device via ADB transport ID."""
        try:
            output = subprocess.check_output(
                ["adb", "-t", transport_id, "shell", "getprop", "ro.build.id"],
                stderr=subprocess.DEVNULL,
                timeout=2
            ).decode().strip()
            log.debug("Build ID for transport %s: %r", transport_id, output)
            return output if output else ""
        except Exception as exc:
            log.debug("get_build_id failed for transport %s: %s", transport_id, exc)
            return ""
