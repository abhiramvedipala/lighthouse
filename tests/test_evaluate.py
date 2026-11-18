import numpy as np
import pytest

from lighthouse.evaluate import Incident, alarm_events, evaluate, point_adjusted_f1

N = 2880
WIN = (0, 1440)  # one day


def flags(**per_service):
    out = {}
    for svc, minutes in per_service.items():
        a = np.zeros(N, dtype=bool)
        a[list(minutes)] = True
        out[svc] = a
    return out


def inc(id, start, end, services=("a",), typ="latency_spike", benign=False):
    return Incident(id, typ, frozenset(services), start, end, benign)


# ---- alarm event merging ---------------------------------------------------------------------

def test_merge_gap_boundary_ten_unflagged_minutes_merge_eleven_do_not():
    assert alarm_events([10, 21]) == [(10, 21)]        # minutes 11..20 unflagged = 10, merges
    assert alarm_events([10, 22]) == [(10, 10), (22, 22)]  # 11 unflagged minutes, splits


def test_adjacent_and_unsorted_flags_merge_into_one_event():
    assert alarm_events([5, 3, 4, 4]) == [(3, 5)]
    assert alarm_events([]) == []


# ---- degenerate inputs -----------------------------------------------------------------------

def test_no_incidents_and_no_flags():
    r = evaluate(flags(a=[]), [], WIN)
    assert r.n_incidents == 0 and r.n_alarm_events == 0
    assert np.isnan(r.precision) and np.isnan(r.recall) and r.f1 == 0.0
    assert r.false_alarms_per_day == 0


def test_incidents_but_no_flags_gives_zero_recall():
    r = evaluate(flags(a=[]), [inc("i1", 100, 110)], WIN)
    assert r.recall == 0.0 and np.isnan(r.precision) and r.f1 == 0.0


def test_flags_but_no_incidents_are_all_false_alarms():
    r = evaluate(flags(a=[100, 300]), [], WIN)
    assert r.precision == 0.0 and np.isnan(r.recall)
    assert r.false_alarms == 2 and r.false_alarms_per_day == 2.0


# ---- tolerance window ------------------------------------------------------------------------

def test_flag_on_last_tolerance_minute_detects_and_one_later_does_not():
    # incident covers minutes 100..109, window ends at 109 + 5 = 114
    assert evaluate(flags(a=[114]), [inc("i", 100, 110)], WIN).recall == 1.0
    miss = evaluate(flags(a=[115]), [inc("i", 100, 110)], WIN)
    assert miss.recall == 0.0 and miss.precision == 0.0


def test_flag_before_start_does_not_detect():
    r = evaluate(flags(a=[99]), [inc("i", 100, 110)], WIN)
    assert r.recall == 0.0


def test_flag_at_exact_start_is_detected_with_zero_delay():
    r = evaluate(flags(a=[100]), [inc("i", 100, 110)], WIN)
    assert r.recall == 1.0 and r.median_delay == 0.0


# ---- one flag, two incidents -----------------------------------------------------------------

def test_one_long_flag_spanning_two_incidents_detects_both_with_one_alarm():
    f = flags(a=range(95, 215))
    r = evaluate(f, [inc("i1", 100, 110), inc("i2", 200, 210)], WIN)
    assert r.n_alarm_events == 1 and r.recall == 1.0 and r.precision == 1.0
    assert [p["delay"] for p in r.per_incident] == [0, 0]  # first flag at/after each start is the start itself


def test_two_separate_alarms_inside_one_incident_are_both_true_positives():
    r = evaluate(flags(a=[100, 130]), [inc("i", 100, 140)], WIN)
    assert r.n_alarm_events == 2 and r.precision == 1.0 and r.recall == 1.0


# ---- services --------------------------------------------------------------------------------

def test_overlapping_incidents_on_different_services_need_their_own_alarm():
    incs = [inc("ia", 100, 120, ("a",)), inc("ib", 105, 125, ("b",))]
    r = evaluate(flags(a=[101], b=[]), incs, WIN)
    assert r.recall == 0.5
    by_id = {p["id"]: p["detected"] for p in r.per_incident}
    assert by_id == {"ia": True, "ib": False}


def test_cascade_incident_is_detected_by_an_alarm_on_any_affected_service():
    cascade = inc("c", 100, 110, ("inv", "ord", "gw"), "dependency_outage")
    r = evaluate(flags(inv=[], ord=[103], gw=[], other=[]), [cascade], WIN)
    assert r.recall == 1.0 and r.precision == 1.0


def test_alarm_on_an_unaffected_service_is_a_false_alarm():
    r = evaluate(flags(a=[], b=[105]), [inc("i", 100, 110, ("a",))], WIN)
    assert r.recall == 0.0 and r.false_alarms == 1


# ---- delay and lead time ---------------------------------------------------------------------

def test_delay_is_first_flag_minus_start():
    r = evaluate(flags(a=[107, 108]), [inc("i", 100, 120)], WIN)
    assert r.median_delay == 7.0


def test_lead_time_versus_static_on_incidents_both_catch():
    incs = [inc("i1", 100, 130), inc("i2", 300, 330), inc("i3", 500, 530)]
    det = flags(a=[103, 305, 502])
    stat = flags(a=[110, 307])  # static misses i3
    r = evaluate(det, incs, WIN, static_flags=stat)
    leads = {p["id"]: p["lead"] for p in r.per_incident}
    assert leads == {"i1": 7, "i2": 2, "i3": None}
    assert r.median_lead == 4.5 and r.n_both == 2
    assert r.n_detector_only == 1 and r.n_static_only == 0


def test_static_only_catches_are_counted():
    r = evaluate(flags(a=[]), [inc("i", 100, 130)], WIN, static_flags=flags(a=[120]))
    assert r.n_static_only == 1 and r.n_detector_only == 0 and np.isnan(r.median_lead)


def test_negative_lead_when_detector_is_later_than_static():
    r = evaluate(flags(a=[115]), [inc("i", 100, 130)], WIN, static_flags=flags(a=[105]))
    assert r.median_lead == -10.0


# ---- false alarms, benign events, windows -----------------------------------------------------

def test_false_alarms_per_day_scale_with_window_length():
    f = flags(a=[100, 400, 800])
    one_day = evaluate(f, [], (0, 1440))
    two_days = evaluate(f, [], (0, 2880))
    assert one_day.false_alarms_per_day == 3.0 and two_days.false_alarms_per_day == 1.5


def test_alarm_during_benign_event_is_a_false_alarm_and_counted_separately():
    incs = [inc("b1", 300, 360, ("a",), "traffic_surge", benign=True), inc("r", 100, 110)]
    r = evaluate(flags(a=[101, 320]), incs, WIN)
    assert r.precision == 0.5 and r.false_alarms == 1
    assert r.benign_false_alarms == 1 and r.benign_events_alarmed == 1 and r.n_benign == 1
    assert r.recall == 1.0  # benign events are not incidents


def test_flags_and_incidents_outside_the_window_are_ignored():
    f = flags(a=[1500, 100])
    r = evaluate(f, [inc("in", 100, 110), inc("out", 1500, 1510)], (0, 1440))
    assert r.n_incidents == 1 and r.n_alarm_events == 1 and r.precision == 1.0


def test_per_type_breakdown():
    incs = [inc("i1", 100, 110, typ="latency_spike"), inc("i2", 300, 310, typ="error_burst"),
            inc("i3", 500, 510, typ="error_burst")]
    r = evaluate(flags(a=[101, 302]), incs, WIN)
    assert r.per_type["latency_spike"]["recall"] == 1.0
    assert r.per_type["error_burst"]["recall"] == 0.5 and r.per_type["error_burst"]["n"] == 2


def test_precision_recall_f1_hand_computed():
    # 4 incidents, detect 3; 3 alarms on incidents + 1 false alarm -> P = 3/4, R = 3/4, F1 = 3/4
    incs = [inc(f"i{k}", 100 + 200 * k, 110 + 200 * k) for k in range(4)]
    r = evaluate(flags(a=[101, 301, 501, 1300]), incs, WIN)
    assert (r.precision, r.recall) == (0.75, 0.75) and r.f1 == pytest.approx(0.75)


# ---- point-adjusted F1 --------------------------------------------------------------------------

def test_point_adjust_rewards_one_flag_with_the_whole_segment():
    f = flags(a=[100])
    i = inc("i", 100, 160)
    assert point_adjusted_f1(f, [i], WIN) == pytest.approx(1.0)  # 60 of 60 minutes credited, no false points
    r = evaluate(f, [i], WIN)
    assert r.f1 == 1.0 and r.point_adjusted_f1 == pytest.approx(1.0)


def test_point_adjust_still_penalises_false_positive_minutes():
    f = flags(a=[100, 500, 501, 502, 503])
    p = point_adjusted_f1(f, [inc("i", 100, 110)], WIN)
    # after adjusting: tp = 10, fp = 4, fn = 0 -> P = 10/14, R = 1
    assert p == pytest.approx(2 * (10 / 14) / (10 / 14 + 1))


def test_point_adjust_is_zero_without_any_hit():
    assert point_adjusted_f1(flags(a=[500]), [inc("i", 100, 110)], WIN) == 0.0
