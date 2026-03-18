"""Persistent per-operation timing log for weighted progress and ETA."""
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_LOG_PATH = Path.home() / ".cache" / "factory_flash" / "timing.json"
_MAX_SAMPLES = 20


class FlashTimingLog:
    """Stores average duration (seconds) per flash operation task name.

    On the first run all weights are equal (uniform).  After that each
    partition's historical average is used so the progress bar advances
    proportionally to real elapsed time.
    """

    def __init__(self):
        self._data: dict[str, list[float]] = {}
        self._load()

    def _load(self):
        try:
            with open(_LOG_PATH) as f:
                self._data = json.load(f)
            log.debug("Timing log loaded: %d entries from %s", len(self._data), _LOG_PATH)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("Could not load timing log: %s", exc)

    def save(self):
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(_LOG_PATH, "w") as f:
                json.dump(self._data, f, indent=2)
            log.debug("Timing log saved: %d entries to %s", len(self._data), _LOG_PATH)
        except Exception as exc:
            log.warning("Could not save timing log: %s", exc)

    def record(self, task: str, duration_sec: float):
        """Record that *task* took *duration_sec* seconds."""
        if not task or duration_sec <= 0:
            return
        samples = self._data.setdefault(task, [])
        samples.append(round(duration_sec, 3))
        if len(samples) > _MAX_SAMPLES:
            del samples[0]

    def avg_duration(self, task: str, fallback: float = 5.0) -> float:
        s = self._data.get(task, [])
        return sum(s) / len(s) if s else fallback

    def weights_for(self, tasks: list[str]) -> list[float]:
        """Return duration-proportional weight for each task (same order)."""
        return [self.avg_duration(t) for t in tasks]
