# Investigation lab

Open **Investigation lab** from the desktop left toolbar (magnifier), the classic
sidebar, or the panel menu. All four tabs work locally. Private sessions require
the existing `evidence.share` permission. No additional service or AI account is
needed. The main exercise and its shared JSON files remain independent.

## Vessel timeline

Choose an exercise vessel, a locally received AIS vessel, or **Unassociated
observations**. **Refresh** takes a new snapshot of already loaded evidence.
Exercise fixes stop at the current replay time. Received AIS history is bounded
by the existing 24-hour / 720-fix-per-vessel store.

The timeline combines received fixes, gaps over 15 minutes, stream boundaries,
locally observed identity declaration changes, loaded satellite associations and
analyst reports. **Open source** shows the original available record, or opens
the existing satellite review. **Show location** centres the map on that event's
historical location. Satellite identity associations remain provisional; separate
unmatched observations are never assigned to a vessel by proximity here.

Identity change times mean when this client observed a changed declaration, not
when it became effective. These events are session-local, bounded to 512, and
start with this version; earlier history is unknown. Reports retain actual
submission times, including reports about an exercise. Exports retain source
records, provenance and UTC timestamps.

## Encounter review

Select **Fictional encounter exercise**, **Current replay**, or **Received AIS
history**, select 2–40 vessels, then **Review selected**. Select a result and use
the slider to replay its supporting observed tracks. Review is manual and uses
a fixed snapshot of the last six hours ending at the newest selected fix.

The first version uses these explicit design assumptions:

| Pattern | Required observed evidence |
|---|---|
| Parallel travel | Within 1 nm for at least 20 min; both at least 3 kn, speed difference at most 2 kn, course difference at most 15 degrees |
| Possible rendezvous | Within 0.5 nm for at least 15 min; both at most 2 kn |
| Repeated close approaches | Three episodes within 0.5 nm, each with at least three samples spanning two minutes; at least ten minutes between episodes and observed separation beyond 1 nm |

Observations match only within 60 seconds, without interpolation. Gaps over
three minutes and changes of stream break a duration. Repeated approaches need
observations through the separation, not missing data. Distinct provenance or
identical vessel IDs cannot form a pair. Implausible positional motion over
80 kn is excluded. Where historical speed/course are absent, motion is derived
from adjacent received positions. Reception times are approximate observations,
not guaranteed simultaneous transmission times.

Patterns near a bundled port (within 3 nm at the sampled beginning, middle or
end) are retained as **Context only**. The Python API also accepts explicit
anchorage circles; the desktop does not currently supply a surveyed anchorage
dataset. Missing port/anchorage context and normal fleet operations can still
produce review leads. These rules are unvalidated, and do not prove coordination,
transfer, concealment or hostile intent. They do not change incident severity.

## Scenario challenge

The challenge forks the exercise vessel at its last available fix at the current
replay position. Set speed, course, simulated wind and AIS availability, then
advance one or five minutes, or press **Play**. Playback advances a fictional
minute every 750 ms. **Pause** stops it; **Reset** starts again from the main replay.
The branch lasts at most three hours. Closing or moving the panel pauses it and
retains the branch in application memory until reset or application exit.

The existing Brain assembler scores observations and the existing fleet engine
computes conditional observation times. Original future AIS and original radar
observations do not enter the new branch. AIS-off motion exists only as labelled
simulation truth: it cannot affect evidence-based position, detection or fleet
estimates until reception resumes. The chart shows received fixes only. The
display exposes observation age, the assumed reachable radius and the uncertainty
of projecting last observed speed/course. No simulated response is dispatched.

**Export branch and assumptions** includes inputs, observed fixes, separate
simulation truth, illustrative cable geometry, fleet assumptions and results.

## Performance comparison

**Run comparison** evaluates the five existing fictional Brain stories using
the same observations for the registered Brain rules and a baseline that alerts
within 1 nm of an illustrative cable. A Brain alert means **Medium or higher**.
The comparison counts alert episodes, not every refresh. Its denominator is
observed vessel-hours, not a claim of continuous regional coverage.

Labels are authored expectations of whether the story merits review, not labels
of criminal activity. They are used only after detection. The panel reports
case-level true/false positives and negatives against these exercise labels.
This is a development demonstration, not an independent test or real-world
accuracy estimate. Do not describe the results as an operational false-alarm rate.

Warning lead is measured to the first observed entry into any evaluated 1 nm
corridor. Negative means the alert was later; a missing alert or corridor entry
has no lead measurement. In particular, the current drag story alerts after its
first corridor entry, and that negative result remains visible.

Exports include all per-story timings, label reasons, metrics, a method version
and a SHA-256 hash of the complete evaluation inputs. Reproduce from the repository:

```powershell
python -m argus.evaluation
python -m unittest tests.test_investigation tests.test_scenario_lab tests.test_evaluation tests.test_desktop_investigation
```
