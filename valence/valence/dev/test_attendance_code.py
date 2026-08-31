from valence.valence.attendance_code import get_attendance_code

BASE_CONTEXT = {
    "day_type": None,
    "double_factor": 1.0,
    "worked_half": None,
    "full_day_hours": 6.0,
}

IN_TIME = "2026-09-01 09:00:00"
OUT_TIME = "2026-09-01 13:00:00"

CASES = [
    ("Normal", "Present full day", {"status": "Present", "working_hours": 8}, {}, "P"),
    ("Normal", "Work From Home reports as P", {"status": "Work From Home", "working_hours": 8}, {}, "P"),
    ("Normal", "Present With Short Leave reports as P", {"status": "Present With Short Leave", "working_hours": 8}, {}, "P"),
    ("Normal", "Absent", {"status": "Absent"}, {}, "A"),
    ("Normal", "Mispunch not reportable", {"status": "Mispunch"}, {}, None),
    ("Normal", "No punch not reportable", {"status": "No punch"}, {}, None),
    ("Normal", "On Duty full day", {"status": "On Duty"}, {}, "TT"),
    ("Normal", "Double shift full", {"status": "Present", "working_hours": 16}, {"double_factor": 2.0}, "2P"),
    ("Normal", "Double shift half", {"status": "Present", "working_hours": 12}, {"double_factor": 1.5}, "2P/A"),

    ("Half day", "Worked first half, other half absent", {"status": "Half Day", "half_day_status": "Absent", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "P/A"),
    ("Half day", "Worked second half, other half absent", {"status": "Half Day", "half_day_status": "Absent", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "Second Half"}, "A/P"),
    ("Half day", "CL with half_day_status Present, worked first", {"status": "Half Day", "leave_type": "Casual Leave", "half_day_status": "Present", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "P/CL"),
    ("Half day", "CL with half_day_status Present, worked second", {"status": "Half Day", "leave_type": "Casual Leave", "half_day_status": "Present", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "Second Half"}, "CL/P"),
    ("Half day", "CL with punches but no half_day_status", {"status": "Half Day", "leave_type": "Casual Leave", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "P/CL"),
    ("Half day", "SL with punches, worked second half", {"status": "Half Day", "leave_type": "Sick Leave", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "Second Half"}, "SL/P"),
    ("Half day", "CL with no punches stays leave over absent", {"status": "Half Day", "leave_type": "Casual Leave"}, {}, "CL/A"),
    ("Half day", "CL with half_day_status Absent overrides punches", {"status": "Half Day", "leave_type": "Casual Leave", "half_day_status": "Absent", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "CL/A"),
    ("Half day", "LWP half day with punches, worked first", {"status": "Half Day", "leave_type": "Leave Without Pay", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "P/L"),
    ("Half day", "LWP half day with no punches", {"status": "Half Day", "leave_type": "Leave Without Pay"}, {}, "L/A"),
    ("Half day", "On Duty half day", {"status": "Half Day", "attendance_request": "AR-0001", "in_time": IN_TIME, "out_time": OUT_TIME}, {"worked_half": "First Half"}, "P/TT"),

    ("Leave", "Casual Leave", {"status": "On Leave", "leave_type": "Casual Leave"}, {}, "CL"),
    ("Leave", "Sick Leave", {"status": "On Leave", "leave_type": "Sick Leave"}, {}, "SL"),
    ("Leave", "Earned Leave", {"status": "On Leave", "leave_type": "Earned Leave"}, {}, "EL"),
    ("Leave", "Compensatory Off", {"status": "On Leave", "leave_type": "Compensatory Off"}, {}, "CO"),
    ("Leave", "Privilege Leave via initials fallback", {"status": "On Leave", "leave_type": "Privilege Leave"}, {}, "PL"),
    ("Leave", "Leave Without Pay full day", {"status": "On Leave", "leave_type": "Leave Without Pay"}, {}, "L/L"),
    ("Leave", "On Leave with no leave type", {"status": "On Leave"}, {}, "A"),

    ("Weekly Off", "Idle weekly off", {"status": "Weekly Off", "working_hours": 0}, {"day_type": "Weekly Off"}, "WO"),
    ("Weekly Off", "Worked full day on weekly off", {"status": "Present", "working_hours": 8}, {"day_type": "Weekly Off"}, "PWO"),
    ("Weekly Off", "Worked half day on weekly off", {"status": "Present", "working_hours": 4}, {"day_type": "Weekly Off"}, "PAW"),
    ("Weekly Off", "Double shift on weekly off", {"status": "Present", "working_hours": 16}, {"day_type": "Weekly Off", "double_factor": 2.0}, "2PWO"),
    ("Weekly Off", "Double half shift on weekly off", {"status": "Present", "working_hours": 12}, {"day_type": "Weekly Off", "double_factor": 1.5}, "2PAW"),
    ("Weekly Off", "Leave on weekly off is not marked", {"status": "On Leave", "leave_type": "Casual Leave", "working_hours": 0}, {"day_type": "Weekly Off"}, "WO"),
    ("Weekly Off", "Punches present but working_hours zero", {"status": "Weekly Off", "working_hours": 0, "in_time": IN_TIME, "out_time": OUT_TIME}, {"day_type": "Weekly Off"}, "WO"),

    ("Holiday", "Idle holiday", {"status": "Holiday", "working_hours": 0}, {"day_type": "Holiday"}, "H"),
    ("Holiday", "Worked full day on holiday", {"status": "Present", "working_hours": 8}, {"day_type": "Holiday"}, "HP"),
    ("Holiday", "Worked half day on holiday", {"status": "Present", "working_hours": 4}, {"day_type": "Holiday"}, "HP/A"),
    ("Holiday", "Double shift on holiday", {"status": "Present", "working_hours": 16}, {"day_type": "Holiday", "double_factor": 2.0}, "2HP"),
    ("Holiday", "Double half shift on holiday", {"status": "Present", "working_hours": 12}, {"day_type": "Holiday", "double_factor": 1.5}, "2HP/A"),
    ("Holiday", "Comp Off on holiday", {"status": "On Leave", "leave_type": "Compensatory Off", "working_hours": 0}, {"day_type": "Holiday"}, "CO/H"),
    ("Holiday", "Holiday is never absent", {"status": "Absent", "working_hours": 0}, {"day_type": "Holiday"}, "H"),
]


def _evaluate():
    rows = []
    for group, label, doc, ctx, expected in CASES:
        context = dict(BASE_CONTEXT)
        context.update(ctx)
        try:
            actual = get_attendance_code(doc, context)
        except Exception as exc:
            actual = "EXCEPTION {0}: {1}".format(type(exc).__name__, exc)
        rows.append((group, label, expected, actual, actual == expected))
    return rows


def run():
    rows = _evaluate()

    print("")
    print("=" * 78)
    print("ATTENDANCE CODE DERIVATION - PURE LOGIC TEST (no database access)")
    print("=" * 78)

    current = None
    for group, label, expected, actual, ok in rows:
        if group != current:
            current = group
            print("")
            print("-- {0} {1}".format(group, "-" * (74 - len(group))))
        print("{0}  {1:<48} expected {2:<8} got {3}".format(
            "PASS" if ok else "FAIL",
            label[:48],
            repr(expected),
            repr(actual),
        ))

    failures = [r for r in rows if not r[4]]

    print("")
    print("=" * 78)
    print("TOTAL {0}    PASSED {1}    FAILED {2}".format(
        len(rows), len(rows) - len(failures), len(failures)
    ))
    print("=" * 78)

    if failures:
        print("")
        print("FAILURES")
        for group, label, expected, actual, _ in failures:
            print("  [{0}] {1}".format(group, label))
            print("      expected {0}  got {1}".format(repr(expected), repr(actual)))

    print("")
    return len(failures)
