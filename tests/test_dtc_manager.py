"""Tests for DTCManager (Diagnostic Trouble Code management).

Covers DTC lifecycle: set, confirm, aging, clear, persistence.
Test IDs include FIT-006 from functional_safety.md Section 9.3.
"""

import json

import pytest

from src.master.dtc_manager import (
    AGING_CYCLES,
    BIT_CONFIRMED,
    BIT_PENDING,
    BIT_TEST_FAILED,
    BIT_WARNING_INDICATOR,
    DTCEntry,
    DTCManager,
    MAX_DTCS,
)


class TestDTCManager:
    """Test DTC storage and lifecycle."""

    def test_set_dtc_pending(self, tmp_path):
        """First occurrence sets pending DTC."""
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        entry = dtc.set_dtc(0xC11029, "CRC_FAILURE")
        assert entry.is_pending
        assert entry.is_test_failed
        assert not entry.is_confirmed
        assert entry.occurrence_count == 1

    def test_set_dtc_confirmed_after_2_cycles(self, tmp_path):
        """Same DTC set twice → confirmed."""
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029, "CRC_FAILURE")
        entry = dtc.set_dtc(0xC11029, "CRC_FAILURE")
        assert entry.is_confirmed
        assert entry.occurrence_count == 2

    def test_clear_single_dtc(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029)
        dtc.set_dtc(0xC11129)
        assert dtc.count == 2
        result = dtc.clear_dtc(0xC11029)
        assert result is True
        assert dtc.count == 1
        assert dtc.get_dtc(0xC11029) is None

    def test_clear_all_dtcs(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029)
        dtc.set_dtc(0xC11129)
        count = dtc.clear_all()
        assert count == 2
        assert dtc.count == 0

    def test_status_byte_bits(self, tmp_path):
        """Verify individual status byte bit fields per ISO 14229."""
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        entry = dtc.set_dtc(0xC11029)
        sb = entry.status_byte
        assert sb & BIT_TEST_FAILED
        assert sb & BIT_PENDING
        assert not (sb & BIT_CONFIRMED)  # Not yet confirmed

        entry = dtc.set_dtc(0xC11029)  # Second time
        sb = entry.status_byte
        assert sb & BIT_CONFIRMED
        assert sb & BIT_WARNING_INDICATOR

    def test_aging_clears_confirmed(self, tmp_path):
        """40 consecutive passing cycles clear confirmed bit."""
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029)
        dtc.set_dtc(0xC11029)  # Confirm
        entry = dtc.get_dtc(0xC11029)
        assert entry.is_confirmed

        for _ in range(AGING_CYCLES):
            dtc.report_passing(0xC11029)

        entry = dtc.get_dtc(0xC11029)
        assert not entry.is_confirmed
        assert not entry.is_pending

    def test_persistence_across_restart(self, tmp_path):
        """DTCs survive close and reopen."""
        path = str(tmp_path / "dtc.json")
        dtc1 = DTCManager(path=path)
        dtc1.set_dtc(0xC11029, "CRC")
        dtc1.set_dtc(0xC11129, "SEQ")
        del dtc1

        dtc2 = DTCManager(path=path)
        assert dtc2.count == 2
        entry = dtc2.get_dtc(0xC11029)
        assert entry is not None
        assert entry.fault_type == "CRC"

    def test_missing_file_creates_new(self, tmp_path):
        """FIT-006: Missing DTC file starts clean, new file created on first set."""
        path = str(tmp_path / "nonexistent" / "dtc.json")
        dtc = DTCManager(path=path)
        assert dtc.count == 0
        dtc.set_dtc(0xC11029)
        assert dtc.count == 1

    def test_max_256_dtcs(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        for i in range(MAX_DTCS):
            dtc.set_dtc(0x100000 + i)
        assert dtc.count == MAX_DTCS
        # 257th should be rejected
        entry = dtc.set_dtc(0xFFFFFF)
        assert dtc.count == MAX_DTCS

    def test_get_all_dtcs(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029)
        dtc.set_dtc(0xC11129)
        all_dtcs = dtc.get_all_dtcs()
        assert len(all_dtcs) == 2
        codes = {e.code for e in all_dtcs}
        assert 0xC11029 in codes
        assert 0xC11129 in codes

    def test_freeze_frame_stored(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        dtc.set_dtc(0xC11029, freeze_frame={"sensor": "proximity", "value": 999})
        entry = dtc.get_dtc(0xC11029)
        assert entry.freeze_frame["sensor"] == "proximity"

    def test_clear_nonexistent_returns_false(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        assert dtc.clear_dtc(0xFFFFFF) is False
