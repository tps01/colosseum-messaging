"""Native Windows Ethernet capture and IPv4 echo timing for SSH autoconfig."""

from __future__ import annotations

import ctypes as ct
import os
import sys
from contextlib import ExitStack
from ipaddress import IPv4Interface
from math import ceil, inf
from pathlib import Path
from struct import Struct
from time import monotonic, sleep
from typing import TYPE_CHECKING

from ifaddr import get_adapters

from colosseum_messaging.exceptions import MessagingCapabilityError

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from ipaddress import IPv4Address

_DEVICE_PREFIX = b"\\Device\\NPF_"
_PCAP_ERRBUF_SIZE = 256
_DLT_EN10MB = 1
_PCAP_OPENFLAG_NOCAPTURE_LOCAL = 8
_PCAP_OPENFLAG_MAX_RESPONSIVENESS = 16
_ETHERNET_HEADER_SIZE = 14
_ARP_ETHERTYPE = b"\x08\x06"
_ARP_IPV4_PACKET_SIZE = 28
_SNAPLEN = _ETHERNET_HEADER_SIZE + _ARP_IPV4_PACKET_SIZE
_POLL_INTERVAL_S = 0.01
_MAX_TIMEOUT_MS = (1 << 32) - 1
_ECHO_REPLY = Struct("=III")  # Address, status and RTT precede any pointers.
_ECHO_DATA = b"colosseum"


class _PcapDevice(ct.Structure):
    pass


_PcapDevice._fields_ = [("next", ct.POINTER(_PcapDevice)), ("name", ct.c_char_p)]


class _PcapHeader(ct.Structure):
    _fields_ = [
        ("seconds", ct.c_int32),
        ("microseconds", ct.c_int32),
        ("captured_length", ct.c_uint32),
        ("original_length", ct.c_uint32),
    ]


def adapter_bindings() -> tuple[dict[str, list[IPv4Interface]], dict[str, str]]:
    bindings: dict[str, list[IPv4Interface]] = {}
    aliases: dict[str, str] = {}
    for adapter in get_adapters():
        name = adapter.name.casefold()
        addresses = [ip for ip in adapter.ips if ip.is_IPv4]
        bindings[name] = [IPv4Interface(f"{ip.ip}/{ip.network_prefix}") for ip in addresses]
        aliases.update((ip.nice_name.casefold(), name) for ip in addresses)
    return bindings, aliases


def _load_pcap() -> ct.CDLL:
    directory = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "Npcap"
    try:
        dll = ct.CDLL(str(directory / "wpcap.dll"))
    except OSError as exc:
        raise MessagingCapabilityError(
            "Windows SSH autoconfig requires Npcap. Install Npcap and ensure its service is running.",
        ) from exc
    dll.pcap_findalldevs.argtypes = [ct.POINTER(ct.POINTER(_PcapDevice)), ct.c_char_p]
    dll.pcap_findalldevs.restype = ct.c_int
    dll.pcap_freealldevs.argtypes = [ct.POINTER(_PcapDevice)]
    dll.pcap_freealldevs.restype = None
    dll.pcap_open.argtypes = [ct.c_char_p, ct.c_int, ct.c_int, ct.c_int, ct.c_void_p, ct.c_char_p]
    dll.pcap_open.restype = ct.c_void_p
    dll.pcap_datalink.argtypes = [ct.c_void_p]
    dll.pcap_datalink.restype = ct.c_int
    dll.pcap_setnonblock.argtypes = [ct.c_void_p, ct.c_int, ct.c_char_p]
    dll.pcap_setnonblock.restype = ct.c_int
    dll.pcap_next_ex.argtypes = [ct.c_void_p, ct.POINTER(ct.POINTER(_PcapHeader)), ct.POINTER(ct.c_void_p)]
    dll.pcap_next_ex.restype = ct.c_int
    dll.pcap_geterr.argtypes = [ct.c_void_p]
    dll.pcap_geterr.restype = ct.c_char_p
    dll.pcap_close.argtypes = [ct.c_void_p]
    dll.pcap_close.restype = None
    return dll


def _capture_error(detail: bytes) -> MessagingCapabilityError:
    message = detail.decode(errors="replace")
    return MessagingCapabilityError(
        f"Windows SSH autoconfig could not access Npcap: {message}. "
        "Check the Npcap service and run elevated if Npcap is configured for administrators only.",
    )


def _devices(dll: ct.CDLL) -> Iterator[tuple[str, bytes]]:
    first = ct.POINTER(_PcapDevice)()
    error = ct.create_string_buffer(_PCAP_ERRBUF_SIZE)
    if dll.pcap_findalldevs(ct.byref(first), error) != 0:
        raise _capture_error(error.value)
    try:
        device = first
        while device:
            name = device.contents.name
            if name.startswith(_DEVICE_PREFIX):
                yield name[len(_DEVICE_PREFIX) :].decode("ascii").casefold(), name
            device = device.contents.next
    finally:
        if first:
            dll.pcap_freealldevs(first)


def _read_arp(dll: ct.CDLL, handle: int) -> tuple[bool, bytes]:
    header = ct.POINTER(_PcapHeader)()
    packet = ct.c_void_p()
    result = dll.pcap_next_ex(handle, ct.byref(header), ct.byref(packet))
    if result < 0:
        raise OSError(dll.pcap_geterr(handle).decode(errors="replace"))
    if result == 0:
        return False, b""
    if header.contents.captured_length < _SNAPLEN:
        return True, b""
    frame = ct.string_at(packet, _SNAPLEN)
    return True, frame if frame[12:14] == _ARP_ETHERTYPE else b""


def _open_adapters(
    dll: ct.CDLL,
    bindings: dict[str, list[IPv4Interface]],
    stack: ExitStack,
) -> list[tuple[str, int]]:
    error = ct.create_string_buffer(_PCAP_ERRBUF_SIZE)
    flags = _PCAP_OPENFLAG_NOCAPTURE_LOCAL | _PCAP_OPENFLAG_MAX_RESPONSIVENESS
    handles = []
    for interface, name in list(_devices(dll)):
        if not bindings.get(interface) or name == b"\\Device\\NPF_Loopback":
            continue
        handle = dll.pcap_open(b"rpcap://" + name, _SNAPLEN, flags, 1, None, error)
        if not handle:
            raise _capture_error(error.value)
        stack.callback(dll.pcap_close, handle)
        if dll.pcap_datalink(handle) != _DLT_EN10MB:
            continue
        if dll.pcap_setnonblock(handle, 1, error) != 0:
            raise _capture_error(error.value)
        handles.append((interface, handle))
    if not handles:
        raise _capture_error(b"no IPv4 Ethernet capture adapters")
    return handles


def arp_frames(
    bindings: dict[str, list[IPv4Interface]],
    timeout: float,
) -> Generator[tuple[str, bytes, bytes], None, None]:
    dll = _load_pcap()
    with ExitStack() as stack:
        handles = _open_adapters(dll, bindings, stack)
        deadline = monotonic() + timeout
        while (remaining := deadline - monotonic()) > 0:
            activity = False
            for interface, handle in handles:
                received, frame = _read_arp(dll, handle)
                activity |= received
                if frame:
                    yield interface, frame[6:12], frame[_ETHERNET_HEADER_SIZE:]
            if not activity:
                sleep(min(_POLL_INTERVAL_S, remaining))


def icmp_rtt(host: IPv4Address, addresses: list[IPv4Interface], timeout: float) -> float:
    if sys.platform != "win32":
        raise MessagingCapabilityError("Windows IP Helper requires a Windows host")
    source = min(
        addresses,
        key=lambda addr: (-addr.network.prefixlen if host in addr.network else 1, int(addr.ip)),
    ).ip
    dll = ct.WinDLL("iphlpapi.dll", use_last_error=True)
    dll.IcmpCreateFile.argtypes = []
    dll.IcmpCreateFile.restype = ct.c_void_p
    dll.IcmpCloseHandle.argtypes = [ct.c_void_p]
    dll.IcmpCloseHandle.restype = ct.c_int
    dll.IcmpSendEcho2Ex.argtypes = [
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_uint32,
        ct.c_uint32,
        ct.c_char_p,
        ct.c_uint16,
        ct.c_void_p,
        ct.c_void_p,
        ct.c_uint32,
        ct.c_uint32,
    ]
    dll.IcmpSendEcho2Ex.restype = ct.c_uint32
    handle = dll.IcmpCreateFile()
    if handle == ct.c_void_p(-1).value:
        raise ct.WinError(ct.get_last_error())
    try:
        reply = ct.create_string_buffer(128 + len(_ECHO_DATA))
        count = dll.IcmpSendEcho2Ex(
            handle,
            None,
            None,
            None,
            int.from_bytes(source.packed, sys.byteorder),
            int.from_bytes(host.packed, sys.byteorder),
            _ECHO_DATA,
            len(_ECHO_DATA),
            None,
            reply,
            len(reply),
            ceil(min(timeout, _MAX_TIMEOUT_MS / 1000) * 1000),
        )
        if count:
            address, status, rtt_ms = _ECHO_REPLY.unpack_from(reply)
            if status == 0 and address == int.from_bytes(host.packed, sys.byteorder):
                return float(rtt_ms) / 1000
        return inf
    finally:
        dll.IcmpCloseHandle(handle)
