from common.codec import Sequencer
from friend_foe.drone_status import DroneStatusMapper
from friend_foe.estimator import FriendFoeEstimator, TrackState
from friend_foe.investigation import InvestigationTrigger
from sensors.weather import PRESETS, UniformWeather

DRONE_SEQ = Sequencer("F1")


def state(st, mode="goto", command_id="c1", track_id=None, t=10.0, drone="F1"):
    msg = {"type": "drone_state", "header": DRONE_SEQ.header(t), "drone_id": drone, "command_id": command_id,
           "state": st, "mode": mode, "position": [1, 2, 60], "heading_deg": 90.0}
    if track_id:
        msg["track_id"] = track_id
    return msg


def command(command_id="c1", track_id="H1", drone="F1", kind="goto"):
    return {"type": "drone_command", "command_id": command_id, "drone_id": drone, "command": kind, "track_id": track_id}


def states_of(statuses):
    return [s["state"] for s in statuses]


def test_accepted_goto_is_assigned_then_en_route():
    m = DroneStatusMapper()
    out = m.from_drone_state(state("accepted", track_id="H1"))
    assert states_of(out) == ["assigned", "en_route"]
    assert all(s["track_id"] == "H1" and s["drone_id"] == "F1" and s["type"] == "investigation_status" for s in out)


def test_accepted_hold_is_only_assigned():
    assert states_of(DroneStatusMapper().from_drone_state(state("accepted", mode="hold", track_id="H1"))) == ["assigned"]


def test_on_station_and_rejected():
    m = DroneStatusMapper()
    assert states_of(m.from_drone_state(state("on_station", mode="hold", track_id="H1"))) == ["on_station"]
    assert states_of(m.from_drone_state(state("rejected", track_id="H1"))) == ["aborted"]


def test_track_comes_from_the_command_when_the_state_has_none():
    m = DroneStatusMapper()
    m.note_command(command("c1", "H1"))
    assert m.from_drone_state(state("on_station", mode="hold", command_id="c1"))[0]["track_id"] == "H1"


def test_patrolling_after_a_check_is_done_even_without_a_track_id():
    m = DroneStatusMapper()
    m.from_drone_state(state("accepted", track_id="H1"))                       # goto H1
    out = m.from_drone_state(state("patrolling", mode="patrol", command_id="c2"))  # return command has no track
    assert states_of(out) == ["done"] and out[0]["track_id"] == "H1"


def test_patrolling_without_an_investigation_says_nothing():
    assert DroneStatusMapper().from_drone_state(state("patrolling", mode="patrol")) == []


def test_lost_command_is_aborted_and_unknown_command_says_nothing():
    m = DroneStatusMapper()
    m.note_command(command("c1", "H1"))
    out = m.from_command_lost("c1", t=20.0)
    assert states_of(out) == ["aborted"] and out[0]["track_id"] == "H1"
    assert m.from_command_lost("nope", t=20.0) == []


def test_status_headers_are_unique_and_sequential():
    m = DroneStatusMapper()
    out = m.from_drone_state(state("accepted", track_id="H1")) + m.from_drone_state(state("on_station", track_id="H1"))
    assert [s["header"]["seq"] for s in out] == [1, 2, 3]
    assert len({s["header"]["msg_id"] for s in out}) == 3


def test_trigger_stops_asking_while_the_drone_works_and_asks_again_after_done():
    weather = UniformWeather(PRESETS["clear"])
    trigger, mapper = InvestigationTrigger(weather, min_suspicious_s=0.0, cooldown_s=5.0), DroneStatusMapper()
    est = FriendFoeEstimator()
    sent, t = [], 0.0
    for k in range(400):                      # 200 s of a track that stays suspicious
        t = k * 0.5
        tr = [TrackState("H1", t, (0, 0, 0), pos_sigma=2.0)]
        sent += [(t, r) for r in trigger.update(t, est.update(t, tr, []), tr)]
        if k == 10 and len(sent) == 1:        # drone accepts the command for the first request
            for s in mapper.from_drone_state(state("accepted", track_id="H1", t=t)):
                trigger.on_status(s, t)
        if k == 200:                          # and is back on patrol at t = 100
            for s in mapper.from_drone_state(state("patrolling", mode="patrol", command_id="c2", t=t)):
                trigger.on_status(s, t)
    times = [x[0] for x in sent]
    assert len(sent) >= 2
    assert times[1] >= 100.0                  # nothing while the drone was active; next ask after done + cooldown
