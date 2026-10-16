import json

import pytest

from common.codec import CodecError, MessageSizeLog, Sequencer, decode, encode, make_header


def beacon(seq=1):
    return {
        "type": "friendly_beacon",
        "header": make_header("F1", 1.5, seq),
        "friend_id": "F1",
        "position": [1.0, 2.0, 3.0],
        "covariance": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    }


def test_roundtrip():
    m = beacon()
    assert decode(encode(m)) == m


def test_encoding_is_compact_utf8_bytes():
    data = encode(beacon())
    assert isinstance(data, bytes) and b" " not in data


def test_corrupted_bytes_raise():
    data = encode(beacon())
    with pytest.raises(CodecError):
        decode(data[: len(data) // 2])
    with pytest.raises(CodecError):
        decode(b"\xff\xfe\x00")


def test_missing_type_header_or_field_raise():
    m = beacon()
    with pytest.raises(CodecError):
        decode(json.dumps({k: v for k, v in m.items() if k != "type"}).encode())
    with pytest.raises(CodecError):
        decode(json.dumps({k: v for k, v in m.items() if k != "header"}).encode())
    del m["header"]["seq"]
    with pytest.raises(CodecError):
        decode(encode(m))


def test_wrong_schema_version_raises():
    m = beacon()
    m["header"]["schema_version"] = 99
    with pytest.raises(CodecError):
        decode(encode(m))


def test_size_log_counts_per_type():
    log = MessageSizeLog()
    sizes = [len(log.encode(beacon(i))) for i in range(3)]
    s = log.summary()["friendly_beacon"]
    assert s["count"] == 3 and s["bytes"] == sum(sizes)
    assert s["avg_bytes"] == sum(sizes) / 3


def test_sequencer_starts_at_one_and_is_unique_across_message_types():
    seq = Sequencer("C2")
    first, second = seq.header(0.0), seq.header(0.5)
    assert (first["seq"], first["msg_id"]) == (1, "C2-1")
    assert (second["seq"], second["msg_id"]) == (2, "C2-2")
    assert first["schema_version"] == 1 and second["t_sent"] == 0.5


def test_sequencers_of_different_sources_are_independent():
    a, b = Sequencer("F1"), Sequencer("F2")
    a.header(0.0)
    assert b.header(0.0)["seq"] == 1


def test_sequencer_headers_decode():
    seq = Sequencer("F1")
    m = {"type": "friendly_beacon", "header": seq.header(1.0), "friend_id": "F1"}
    assert decode(encode(m))["header"]["msg_id"] == "F1-1"


def test_precision_shrinks_messages_and_keeps_small_values():
    m = beacon()
    m["position"] = [123.45678901234567, 2.0000000000000004, 3.1415926535897932]
    m["covariance"] = [[0.00041234567890123, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert len(encode(m, precision=6)) < len(encode(m))
    d = decode(encode(m, precision=6))
    assert d["position"] == [123.457, 2.0, 3.14159]
    assert d["covariance"][0][0] == pytest.approx(0.000412346, rel=1e-6)


def test_precision_leaves_integers_text_and_the_input_alone():
    m = beacon()
    before = json.dumps(m)
    d = decode(encode(m, precision=3))
    assert d["header"]["seq"] == 1 and d["friend_id"] == "F1" and d["type"] == "friendly_beacon"
    assert json.dumps(m) == before


def test_no_precision_is_lossless():
    m = beacon()
    m["position"] = [123.45678901234567, 0.1, 0.2]
    assert decode(encode(m)) == m


def test_size_log_uses_its_precision():
    m = beacon()
    m["position"] = [123.45678901234567, 2.0000000000000004, 3.1415926535897932]
    assert len(MessageSizeLog(precision=6).encode(m)) < len(MessageSizeLog().encode(m))