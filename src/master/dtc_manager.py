"""DTC (Diagnostic Trouble Code) Manager per ISO 14229 (UDS).

Manages DTC storage, status byte management, aging, and persistence
per functional_safety.md Section 5.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DTC_PATH = "/var/lib/zenoh-master/dtc_store.json"
MAX_DTCS = 256

# ISO 14229 DTC Status Byte Bits
BIT_TEST_FAILED = 0x01                    # bit 0
BIT_TEST_FAILED_THIS_CYCLE = 0x02        # bit 1
BIT_PENDING = 0x04                        # bit 2
BIT_CONFIRMED = 0x08                      # bit 3
BIT_TEST_NOT_COMPLETED_SINCE_CLEAR = 0x10 # bit 4
BIT_TEST_FAILED_SINCE_CLEAR = 0x20       # bit 5
BIT_TEST_NOT_COMPLETED_THIS_CYCLE = 0x40  # bit 6
BIT_WARNING_INDICATOR = 0x80              # bit 7

AGING_CYCLES = 40  # Consecutive passing cycles to clear confirmed


@dataclass
class DTCEntry:
    """Single DTC entry with ISO 14229 status byte."""
    code: int
    status_byte: int = 0
    fault_type: str = ""
    occurrence_count: int = 0
    first_seen_ms: int = 0
    last_seen_ms: int = 0
    passing_cycles: int = 0
    freeze_frame: dict = field(default_factory=dict)

    @property
    def is_pending(self) -> bool:
        return bool(self.status_byte & BIT_PENDING)

    @property
    def is_confirmed(self) -> bool:
        return bool(self.status_byte & BIT_CONFIRMED)

    @property
    def is_test_failed(self) -> bool:
        return bool(self.status_byte & BIT_TEST_FAILED)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "status_byte": self.status_byte,
            "fault_type": self.fault_type,
            "occurrence_count": self.occurrence_count,
            "first_seen_ms": self.first_seen_ms,
            "last_seen_ms": self.last_seen_ms,
            "passing_cycles": self.passing_cycles,
            "freeze_frame": self.freeze_frame,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DTCEntry:
        return cls(
            code=data["code"],
            status_byte=data.get("status_byte", 0),
            fault_type=data.get("fault_type", ""),
            occurrence_count=data.get("occurrence_count", 0),
            first_seen_ms=data.get("first_seen_ms", 0),
            last_seen_ms=data.get("last_seen_ms", 0),
            passing_cycles=data.get("passing_cycles", 0),
            freeze_frame=data.get("freeze_frame", {}),
        )


class DTCManager:
    """DTC storage, status management, and persistence.

    DTC lifecycle (Section 5.3):
      Fault detected → pendingDTC set
      Same fault 2 cycles → confirmedDTC set
      Fault resolved 40 cycles → confirmedDTC cleared (aging)
      Diagnostic clear request → full reset
    """

    def __init__(self, path: str | None = None):
        self._path = Path(path) if path else Path(DEFAULT_DTC_PATH)
        self._lock = threading.Lock()
        self._dtcs: dict[int, DTCEntry] = {}
        self._load()

    def set_dtc(
        self,
        code: int,
        fault_type: str = "",
        freeze_frame: dict | None = None,
    ) -> DTCEntry:
        """Set or update a DTC.

        First occurrence sets pending. Second cycle confirms.

        Args:
            code: DTC code (e.g., 0xC11029).
            fault_type: Description of the fault.
            freeze_frame: Optional snapshot data at time of fault.

        Returns:
            The DTCEntry after update.
        """
        with self._lock:
            now_ms = int(time.time() * 1000)

            if code in self._dtcs:
                entry = self._dtcs[code]
                entry.occurrence_count += 1
                entry.last_seen_ms = now_ms
                entry.passing_cycles = 0
                entry.status_byte |= BIT_TEST_FAILED
                entry.status_byte |= BIT_TEST_FAILED_THIS_CYCLE
                entry.status_byte |= BIT_TEST_FAILED_SINCE_CLEAR
                entry.status_byte |= BIT_PENDING

                # Confirm after 2+ occurrences
                if entry.occurrence_count >= 2:
                    entry.status_byte |= BIT_CONFIRMED
                    entry.status_byte |= BIT_WARNING_INDICATOR
            else:
                if len(self._dtcs) >= MAX_DTCS:
                    logger.warning("DTC store full (%d), cannot add 0x%06X", MAX_DTCS, code)
                    return DTCEntry(code=code)
                entry = DTCEntry(
                    code=code,
                    status_byte=BIT_TEST_FAILED | BIT_TEST_FAILED_THIS_CYCLE | BIT_PENDING | BIT_TEST_FAILED_SINCE_CLEAR,
                    fault_type=fault_type,
                    occurrence_count=1,
                    first_seen_ms=now_ms,
                    last_seen_ms=now_ms,
                    freeze_frame=freeze_frame or {},
                )
                self._dtcs[code] = entry

            self._save()
            return entry

    def report_passing(self, code: int) -> None:
        """Report a passing test cycle for a DTC (aging).

        After AGING_CYCLES consecutive passes, the confirmed bit is cleared.
        """
        with self._lock:
            if code not in self._dtcs:
                return
            entry = self._dtcs[code]
            entry.status_byte &= ~BIT_TEST_FAILED
            entry.status_byte &= ~BIT_TEST_FAILED_THIS_CYCLE
            entry.passing_cycles += 1

            if entry.passing_cycles >= AGING_CYCLES:
                entry.status_byte &= ~BIT_CONFIRMED
                entry.status_byte &= ~BIT_WARNING_INDICATOR
                entry.status_byte &= ~BIT_PENDING

            self._save()

    def clear_dtc(self, code: int) -> bool:
        """Clear a single DTC (UDS 0x14 equivalent).

        Returns:
            True if DTC was found and cleared.
        """
        with self._lock:
            if code in self._dtcs:
                del self._dtcs[code]
                self._save()
                return True
            return False

    def clear_all(self) -> int:
        """Clear all DTCs.

        Returns:
            Number of DTCs cleared.
        """
        with self._lock:
            count = len(self._dtcs)
            self._dtcs.clear()
            self._save()
            return count

    def get_dtc(self, code: int) -> DTCEntry | None:
        """Get a single DTC entry."""
        with self._lock:
            return self._dtcs.get(code)

    def get_all_dtcs(self) -> list[DTCEntry]:
        """Get all stored DTCs."""
        with self._lock:
            return list(self._dtcs.values())

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._dtcs)

    # --- Persistence ---

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            for entry_data in data.get("dtcs", []):
                entry = DTCEntry.from_dict(entry_data)
                self._dtcs[entry.code] = entry
            logger.info("Loaded %d DTCs from %s", len(self._dtcs), self._path)
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning("Failed to load DTC store: %s", e)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"dtcs": [e.to_dict() for e in self._dtcs.values()]}
            with open(self._path, "w") as f:
                json.dump(data, f, separators=(",", ":"))
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.error("Failed to save DTC store: %s", e)
