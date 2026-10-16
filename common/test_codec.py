import json

import pytest

from common.codec import CodecError, MessageSizeLog, decode, encode, make_header


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
