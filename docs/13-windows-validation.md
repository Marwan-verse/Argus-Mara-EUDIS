# Windows regression fixes — 14 October 2026

These fixes were developed on `codex/windows-regression-fixes`, based on main
after PR #12. The results below record validation before integration.

## Causes and changes

- **AIS archive initialization and publication:** opening a directory through
  `os.open` for POSIX-style fsync fails on Windows. Flushing a read-only file
  descriptor also fails there. The archive now flushes writable file handles,
  keeps directory syncing on POSIX and uses Windows `MoveFileExW` replacement
  with write-through for same-volume chunk publication. Errors still stop
  collection and retain source journals; recovery remains idempotent.
- **Recorder console output:** the decorative arrow in the completion message
  cannot be encoded by a cp1252 Windows console. The message now uses ASCII;
  the recorder pipeline test explicitly exercises cp1252 output.
- **Timezone data:** Windows does not provide the IANA database used by Arrow
  timestamp conversion. The optional recorder/live requirements now include
  `tzdata` on Windows.
- **Native test isolation:** the selected-path fixture could age beyond its
  24-hour retention window, hidden-window pinch tests depended on the real
  cursor, and the AIS window test could connect to an external live provider.
  The tests now use a fixture clock, controlled pointer hit-testing and disabled
  external autoconnection. Runtime freshness and gesture behavior are unchanged.
- **CI:** validate Python 3.11 and 3.12 on both Ubuntu and Windows runners.

## Verification

- Full Windows suite on the Lenovo (Python 3.14): **222 tests passed**, including
  native Tk windows. No global live-AIS override was needed.
- Disposable Python 3.12 Linux container: **48 live-service tests passed**,
  including archive recovery, capacity, synthetic HTTP/WebSocket and shutdown.
- Browser replay checks and all **7 live-browser state tests passed**.
- `scripts/check_contracts.py`, `run_gui.py --check` and `git diff --check` passed.
- File-flush and atomic-publication fault tests confirm collection stops and
  journals remain available for recovery.

All AIS fixtures are simulated; no genuine upstream API key is used. Neither
demo JSON contract nor the human approval workflow changed. The expanded CI
matrix validates both platforms on future pull requests; remote results are
recorded in the pull request checks separately from these local measurements.

Windows has no CRT directory-fsync equivalent. File flushing and process-crash
recovery do not establish universal sudden-power-loss guarantees for directory
metadata. See [Python fsync](https://docs.python.org/3/library/os.html#os.fsync)
and [Microsoft MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw).
