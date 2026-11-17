"""Замеры собственного процесса: CPU, private bytes и GPU (best effort)."""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_QUERY_INFORMATION = 0x0400


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class ProcessSampler:
    def __init__(self, pid: int | None = None):
        self.pid = pid or os.getpid()
        self._kernel32 = ctypes.windll.kernel32
        self._psapi = ctypes.windll.psapi
        self._handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
        if not self._handle:
            raise OSError("OpenProcess failed")

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = 0

    def cpu_seconds(self) -> float:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = self._kernel32.GetProcessTimes(
            self._handle, ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel), ctypes.byref(user))
        if not ok:
            raise OSError("GetProcessTimes failed")
        to_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # noqa: E731
        return (to_int(kernel) + to_int(user)) / 10_000_000.0

    def private_bytes(self) -> int:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        ok = self._psapi.GetProcessMemoryInfo(
            self._handle, ctypes.byref(counters), counters.cb)
        if not ok:
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.PrivateUsage)

    def working_set(self) -> int:
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        self._psapi.GetProcessMemoryInfo(self._handle, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize)


def total_ram_bytes() -> int:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return int(status.ullTotalPhys)


def gpu_percent(pid: int) -> float | None:
    """Суммарная загрузка GPU-движков процесса через счётчики Windows."""
    script = (
        "$s=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop)"
        ".CounterSamples | Where-Object { $_.InstanceName -like 'pid_%d_*' }; "
        "if ($s) { ($s | Measure-Object -Property CookedValue -Sum).Sum } else { 0 }" % pid
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        text = (result.stdout or "").strip().replace(",", ".")
        return float(text) if text else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]
