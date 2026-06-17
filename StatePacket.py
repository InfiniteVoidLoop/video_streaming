import json


MAGIC = "VS_STATE_V1"
STATE_UPDATE = "STATE_UPDATE"

READY = "READY"
PLAYING = "PLAYING"
PAUSED = "PAUSED"
STOPPED = "STOPPED"

VALID_STATES = {READY, PLAYING, PAUSED, STOPPED}


def encode_state_packet(state, version, is_server=True):
    """Encode a stream state update for UDP multicast transport."""
    if state not in VALID_STATES:
        raise ValueError("Invalid stream state: " + str(state))

    packet = {
        "magic": MAGIC,
        "is_server": bool(is_server),
        "type": STATE_UPDATE,
        "state": state,
        "version": int(version),
    }
    return json.dumps(packet, separators=(",", ":")).encode("utf-8")


def decode_state_packet(data):
    """Decode and validate a stream state update packet."""
    packet = json.loads(data.decode("utf-8"))

    if packet.get("magic") != MAGIC:
        raise ValueError("Invalid state packet magic")
    if packet.get("type") != STATE_UPDATE:
        raise ValueError("Invalid state packet type")
    if packet.get("state") not in VALID_STATES:
        raise ValueError("Invalid stream state: " + str(packet.get("state")))

    return {
        "is_server": bool(packet.get("is_server")),
        "state": packet["state"],
        "version": int(packet.get("version", 0)),
    }
