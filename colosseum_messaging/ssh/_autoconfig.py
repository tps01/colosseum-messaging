"""Passive Ethernet ARP discovery and ICMP timing on the local Linux host."""

from __future__ import annotations

import socket
import struct
import sys
from functools import lru_cache
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from math import inf, isfinite
from secrets import token_bytes
from time import monotonic
from typing import TYPE_CHECKING, cast

from colosseum.config.loader import ConfigError
from colosseum.logging import get_logger

from colosseum_messaging.exceptions import MessagingCapabilityError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

_logger = get_logger("colosseum.messaging")

_ETH_P_ARP = 0x0806
_ETH_P_IPV4 = 0x0800
_ARPHRD_ETHER = 1
# Hardware/protocol types, address sizes, opcode, sender MAC and IPv4, target fields.
_ARP_IPV4 = struct.Struct("!HHBBH6s4s6x4x")
_ARP_REQUEST_REPLY = (1, 2)
_ICMP_ECHO_REQUEST = 8
_IPV4_MAX_HEADER_BYTES = 60


def _ipv4_bindings() -> dict[str, list[IPv4Interface]]:
    from ifaddr import get_adapters

    bindings: dict[str, list[IPv4Interface]] = {}
    for adapter in get_adapters():
        # Linux may report IPv4 aliases as eth0:1, but packets arrive on eth0.
        interface = adapter.name.split(":", 1)[0]
        bindings.setdefault(interface, []).extend(
            IPv4Interface(f"{ip.ip}/{ip.network_prefix}") for ip in adapter.ips if ip.is_IPv4
        )
    return bindings


def _blocked_networks(
    blacklist: str | Sequence[str] | None,
    bindings: dict[str, list[IPv4Interface]],
) -> set[IPv4Network]:
    entries = [blacklist] if isinstance(blacklist, str) else blacklist or ()
    blocked: set[IPv4Network] = set()
    for entry in entries:
        name = entry.strip().casefold()
        if "/" in name:
            try:
                blocked.add(IPv4Network(name, strict=False))
            except ValueError as exc:
                raise ConfigError(f"Invalid SSH autoconfig IPv4 blacklist network: {entry!r}") from exc
            continue
        networks = {
            binding.network
            for interface, addresses in bindings.items()
            for binding in addresses
            if name in (interface.casefold(), str(binding.ip))
        }
        if not networks:
            _logger.warning("SSH autoconfig blacklist entry not found: %s", entry)
        blocked.update(networks)
    return blocked


@lru_cache(maxsize=256)
def _vendor_name(prefix: bytes) -> str:
    from netaddr import OUI, NotRegisteredError

    try:
        return cast("str", OUI(int.from_bytes(prefix, "big")).registration().org).casefold()
    except NotRegisteredError:
        return ""


def _listen_for_arp(timeout: float) -> Iterator[tuple[str, bytes, IPv4Address]]:
    # AF_PACKET/SOCK_DGRAM returns the Ethernet source in sockaddr_ll and the ARP payload separately.
    with socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, socket.htons(_ETH_P_ARP)) as capture:
        deadline = monotonic() + timeout
        while (remaining := deadline - monotonic()) > 0:
            capture.settimeout(remaining)
            try:
                payload, address = capture.recvfrom(_ARP_IPV4.size)
            except socket.timeout:
                break
            interface, _, packet_type, hardware_type, ethernet_source = cast(
                "tuple[str, int, int, int, bytes]",
                address,
            )
            if (
                packet_type == socket.PACKET_OUTGOING
                or hardware_type != _ARPHRD_ETHER
                or len(payload) < _ARP_IPV4.size
            ):
                continue
            hardware, protocol, mac_size, ip_size, opcode, sender_mac, sender_ip = _ARP_IPV4.unpack(payload)
            if (
                (hardware, protocol, mac_size, ip_size) == (_ARPHRD_ETHER, _ETH_P_IPV4, 6, 4)
                and opcode in _ARP_REQUEST_REPLY
                and sender_mac == ethernet_source
            ):
                yield interface, ethernet_source, IPv4Address(sender_ip)


def _icmp_rtt(host: IPv4Address, interface: str, timeout: float) -> float:
    # Use a random identifier, sequence and payload to recognize the corresponding reply.
    request = struct.pack("!BBH", _ICMP_ECHO_REQUEST, 0, 0) + token_bytes(12)
    checksum = sum(word for (word,) in struct.iter_unpack("!H", request))
    checksum = (checksum & 0xFFFF) + (checksum >> 16)
    checksum = (checksum & 0xFFFF) + (checksum >> 16)
    request = request[:2] + struct.pack("!H", checksum ^ 0xFFFF) + request[4:]
    with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode() + b"\0")
        try:
            probe.connect((str(host), 0))
            start = monotonic()
            probe.send(request)
            while (remaining := start + timeout - monotonic()) > 0:
                probe.settimeout(remaining)
                reply = probe.recv(_IPV4_MAX_HEADER_BYTES + len(request))
                header_size = (reply[0] & 0x0F) * 4
                if reply[header_size : header_size + 2] == b"\0\0" and reply[header_size + 4 :] == request[4:]:
                    return monotonic() - start
        except OSError as exc:
            _logger.debug("SSH autoconfig ICMP probe to %s on %s: %s", host, interface, exc)
    return inf


def _candidates(
    source: str,
    listen_timeout: float,
    blacklist: str | Sequence[str] | None,
) -> dict[IPv4Address, set[str]]:
    bindings = _ipv4_bindings()
    blocked = _blocked_networks(blacklist, bindings)
    excluded_ips = {IPv4Address("255.255.255.255")}
    for addresses in bindings.values():
        excluded_ips.update(binding.ip for binding in addresses)
        excluded_ips.update(
            binding.network.broadcast_address for binding in addresses if binding.network.prefixlen < 31
        )
    hosts: dict[IPv4Address, set[str]] = {}
    for interface, mac, host in _listen_for_arp(listen_timeout):
        if host in excluded_ips or host.is_unspecified or host.is_multicast or host.is_loopback:
            continue
        if any(host in network for network in blocked):
            continue
        if source in mac.hex(":") or source in _vendor_name(mac[:3]):
            hosts.setdefault(host, set()).add(interface)
    return hosts


def discover_ssh_hosts(
    source: str,
    *,
    listen_timeout: float,
    probe_timeout: float,
    blacklist: str | Sequence[str] | None,
) -> list[str]:
    source = source.strip().casefold()
    if not source:
        raise ConfigError("SSH autoconfig requires a nonempty Ethernet source substring")
    for name, value in (("listen_timeout", listen_timeout), ("probe_timeout", probe_timeout)):
        if not isfinite(value) or value <= 0:
            raise ConfigError(f"SSH autoconfig {name} must be a finite positive number of seconds")
    if not sys.platform.startswith("linux"):
        raise MessagingCapabilityError("SSH autoconfig requires a Linux host for Ethernet ARP capture")

    _logger.info("SSH autoconfig listening for ARP sources matching %r for %g s", source, listen_timeout)
    try:
        candidates = _candidates(source, listen_timeout, blacklist)
        timings = [
            (min(_icmp_rtt(host, interface, probe_timeout) for interface in sorted(interfaces)), host)
            for host, interfaces in candidates.items()
        ]
    except PermissionError as exc:
        raise MessagingCapabilityError("SSH autoconfig requires CAP_NET_RAW for ARP capture and ICMP timing") from exc
    except OSError as exc:
        raise ConfigError(f"SSH autoconfig network error: {exc}") from exc
    if not timings:
        raise ConfigError(f"SSH autoconfig observed no matching IPv4 ARP senders for {source!r}")
    hosts = []
    for ssh_id, (rtt, host) in enumerate(sorted(timings), start=1):
        _logger.info(
            "SSH autoconfig assigned ssh_id=%d host=%s RTT=%s",
            ssh_id,
            host,
            f"{rtt * 1000:.3f} ms" if isfinite(rtt) else "unavailable",
        )
        hosts.append(str(host))
    return hosts
