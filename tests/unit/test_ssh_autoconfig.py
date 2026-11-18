"""SSH autoconfig through the public messaging namespace."""

import socket
import struct
import sys
from ipaddress import IPv4Address, IPv4Interface
from math import inf
from unittest.mock import MagicMock, Mock, call

import colosseum as col
import colosseum.context as context_module
import pytest
from colosseum.config.loader import ConfigError
from colosseum_messaging.ssh import _autoconfig

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux packet sockets")

_XILINX_MAC = bytes.fromhex("000a35010203")
_OTHER_MAC = bytes.fromhex("020102030405")


def _arp(host, *, interface="eth0", ethernet_source=_XILINX_MAC, sender_mac=None, opcode=1):
    payload = struct.pack(
        "!HHBBH6s4s6s4s",
        1,
        0x0800,
        6,
        4,
        opcode,
        sender_mac or ethernet_source,
        IPv4Address(host).packed,
        bytes(6),
        IPv4Address("192.168.1.100").packed,
    )
    return payload, (interface, 0x0806, socket.PACKET_BROADCAST, 1, ethernet_source)


@pytest.fixture
def active_config(monkeypatch, tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[messaging.ssh]\nssh_id = 1\nhost = "old.example"\nusername = "old"\n'
        '[messaging.http]\nhttp_id = 1\nbase_url = "http://bench.example"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(context_module, "_ACTIVE_CONTEXT", None)
    col.config.load_config(path, no_artifacts=True)
    return context_module.get_context()


def test_arp_discovery_ranks_eligible_hosts_and_refreshes_ssh_clients(monkeypatch, active_config):
    monkeypatch.setattr(
        _autoconfig,
        "_ipv4_bindings",
        lambda: {
            "eth0": [IPv4Interface("192.168.1.1/24"), IPv4Interface("192.168.2.1/24")],
            "eth1": [IPv4Interface("10.1.0.1/24"), IPv4Interface("10.2.0.1/24")],
            "eth2": [IPv4Interface("172.16.0.1/24")],
        },
    )
    capture = MagicMock()
    capture.__enter__.return_value = capture
    capture.recvfrom.side_effect = [
        _arp("192.168.1.20"),
        _arp("192.168.1.2", opcode=2),
        _arp("192.168.1.3"),
        _arp("192.168.1.20"),
        _arp("192.168.2.2"),
        _arp("10.1.0.2", interface="eth1"),
        _arp("10.2.0.2", interface="eth1"),
        _arp("172.16.0.2", interface="eth2"),
        _arp("192.168.1.4", ethernet_source=_OTHER_MAC),
        _arp("192.168.1.5", ethernet_source=_OTHER_MAC, sender_mac=_XILINX_MAC),
        _arp("192.168.1.1"),
        _arp("192.168.1.255"),
        _arp("0.0.0.0"),
        _arp("198.51.100.2"),
        socket.timeout(),
    ]
    packet_socket = Mock(return_value=capture)
    monkeypatch.setattr(_autoconfig.socket, "socket", packet_socket)
    rtt = Mock(side_effect=[0.035, inf, 0.010, inf])
    monkeypatch.setattr(_autoconfig, "_icmp_rtt", rtt)
    ssh_client = Mock()
    http_client = Mock()
    active_config.resource_cache.update({"messaging:ssh:1": ssh_client, "messaging:http:1": http_client})

    store = col.messaging.ssh.autoconfig(
        source="xILinX",
        username="bench",
        blacklist=["eth1", "192.168.2.1", "172.16.0.0/24"],
        probe_timeout=0.25,
    )

    assert store is active_config.config
    assert store.list_items("messaging.ssh") == [
        {"ssh_id": 1, "host": "192.168.1.3", "username": "bench"},
        {"ssh_id": 2, "host": "192.168.1.20", "username": "bench"},
        {"ssh_id": 3, "host": "192.168.1.2", "username": "bench"},
        {"ssh_id": 4, "host": "198.51.100.2", "username": "bench"},
    ]
    assert store.require_item("messaging.http", 1)["base_url"] == "http://bench.example"
    packet_socket.assert_called_once_with(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(0x0806))
    assert rtt.call_args_list == [
        call(IPv4Address("192.168.1.20"), "eth0", 0.25),
        call(IPv4Address("192.168.1.2"), "eth0", 0.25),
        call(IPv4Address("192.168.1.3"), "eth0", 0.25),
        call(IPv4Address("198.51.100.2"), "eth0", 0.25),
    ]
    ssh_client.close.assert_called_once_with()
    assert active_config.resource_cache == {"messaging:http:1": http_client}


def test_no_matches_leave_active_ssh_config_usable(monkeypatch, active_config):
    monkeypatch.setattr(_autoconfig, "_ipv4_bindings", lambda: {})
    monkeypatch.setattr(_autoconfig, "_listen_for_arp", lambda timeout: iter(()))
    original = active_config.config
    ssh_client = Mock()
    active_config.resource_cache["messaging:ssh:1"] = ssh_client

    with pytest.raises(ConfigError, match="no matching IPv4 ARP senders"):
        col.messaging.ssh.autoconfig(source="Xilinx")

    assert active_config.config is original
    assert active_config.resource_cache["messaging:ssh:1"] is ssh_client
    ssh_client.close.assert_not_called()


def test_icmp_probe_times_only_the_matching_echo_reply(monkeypatch):
    probe = MagicMock()
    probe.__enter__.return_value = probe
    monkeypatch.setattr(_autoconfig.socket, "socket", Mock(return_value=probe))
    monkeypatch.setattr(_autoconfig, "token_bytes", lambda size: b"A" * size)
    monkeypatch.setattr(_autoconfig, "monotonic", Mock(side_effect=[1.0, 1.001, 1.002, 1.025]))

    # IPv4 header with an option, followed by two ICMP Echo Replies.
    ipv4_header = b"\x46" + bytes(23)
    probe.recv.side_effect = [ipv4_header + bytes(16), ipv4_header + bytes(4) + b"A" * 12]

    assert _autoconfig._icmp_rtt(IPv4Address("192.168.1.2"), "eth0", 0.25) == pytest.approx(0.025)
    probe.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, b"eth0\0")
    probe.connect.assert_called_once_with(("192.168.1.2", 0))
    (request,), _ = probe.send.call_args
    assert request[:2] == bytes((8, 0))
    assert sum(word for (word,) in struct.iter_unpack("!H", request)) % 0xFFFF == 0
