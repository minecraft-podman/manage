#!/usr/bin/python3
import enum
import dataclasses
import struct
import asyncio
import weakref
import logging

log = logging.getLogger(__name__)


class InvalidPacket(Exception):
    """
    The given buffer is not a valid packet
    """


# Based on https://wiki.vg/RCON
class PacketType(enum.IntEnum):
    LOGIN = 3
    COMMAND = 2
    RESPONSE = 0


@dataclasses.dataclass
class Packet:
    request_id: int
    type: PacketType
    payload: bytes

    def to_bytes(self):
        """
        Serialize this packet into bytes
        """
        data = struct.pack("<ii", self.request_id, self.type) + self.payload + b"\x00\x00"
        return struct.pack("<i", len(data)) + data

    @classmethod
    def _from_bytes(cls, buffer, exact):
        if len(buffer) < 12:
            raise InvalidPacket
        rest_length, req, typ = struct.unpack("<iii", buffer[:12])
        total_length = rest_length + 4
        rest = buffer[12:total_length]
        if len(buffer) < total_length:
            raise InvalidPacket

        if exact and len(buffer) != total_length:
            raise InvalidPacket

        payload, padding = rest[:-2], rest[-2:]
        if padding != b"\x00\x00":
            raise InvalidPacket

        typ = PacketType(typ)
        return cls(request_id=req, type=typ, payload=payload), total_length

    @classmethod
    def from_bytes(cls, buffer, *, exact=False):
        """
        Deserialize a packet from bytes.

        If exact is True, the entire buffer must be consumed.
        """
        self, _ = cls.from_bytes(buffer, exact)
        return self

    @classmethod
    def scan_for_packet(cls, buffer):
        """
        Scan a buffer for a packet.

        Returns a Packet or None and the used buffer length.
        """
        if b'\x00\x00' not in buffer:
            # Can't have a packet.
            return None, 0

        for i in range(0, len(buffer)):
            try:
                packet, used = cls._from_bytes(buffer[i:], exact=False)
            except InvalidPacket:
                continue
            else:
                return packet, i + used
        else:
            return None, 0


# Stolen from spiroapi_client, which is mine
class Disconnected(Exception):
    """
    Not currently connected to the server
    """


class BackpressureManager:
    """
    Handles backpressure and gating access to a callable.

    Raises a BrokenPipeError if called while shutdown.

    NOTE: If a coroutine is passed, it will have to be double-awaited.
    """

    def __init__(self, func):
        self._func = func
        self._is_blocked = asyncio.Event()
        self._call_exception = None

        # Put us in a known state
        self.continue_calls()

    def pause_calls(self):
        """
        Pause calling temporarily.

        Does nothing if closed.
        """
        if self._call_exception is None:
            self._is_blocked.clear()

    def continue_calls(self):
        """
        Continue calling.

        Does nothing if closed.
        """
        if self._call_exception is None:
            self._is_blocked.set()

    def shutdown(self, exception=ConnectionError):
        """
        Causes calls to error.
        """
        self._call_exception = exception
        self._is_blocked.clear()

    async def __call__(self, *pargs, **kwargs):
        await self._is_blocked.wait()
        if self._call_exception is None:
            return self._func(*pargs, **kwargs)
        else:
            raise Disconnected from self._call_exception


class AuthenticationError(Exception):
    """
    Authentication failed.
    """


class RconProtocol(asyncio.BufferedProtocol):
    _transport = None
    _last_request_id = 0

    def __init__(self):
        self._buffer = bytearray()
        self._buff_size = 0
        self._write_proxy = BackpressureManager(self._real_write)
        self._write_proxy.pause_calls()
        self._response_queues = weakref.WeakValueDictionary()

    # asyncio callbacks
    def connection_made(self, transport):
        self._transport = transport
        self._write_proxy.continue_calls()

    def get_buffer(self, sizehint):
        if sizehint <= 0:
            sizehint = 1024
        if len(self._buffer) < sizehint:
            self._buffer += bytearray(sizehint - len(self._buffer))

        return self._buffer

    def buffer_updated(self, nbytes):
        self._buff_size += nbytes
        while True:
            consumed = self.process_data(self._buffer[:self._buff_size])

            if consumed is None:
                break
            else:
                del self._buffer[:consumed]
                self._buff_size -= consumed

    def process_data(self, buff):
        pack, used = Packet.scan_for_packet(self._buffer[:self._buff_size])
        if pack is None:
            return None
        else:
            self._received_packet(pack)
            return used

    def eof_received(self):
        # Do nothing, I guess
        pass

    def connection_lost(self, exc):
        self._write_proxy.shutdown(exc)
        for q in self._response_queues.values():
            q.put_nowait(exc)

    def pause_writing(self):
        self._write_proxy.pause_calls()

    def resume_writing(self):
        self._write_proxy.continue_calls()

    # User-facing stuff
    def _received_packet(self, packet):
        log.debug("recv:", packet)
        if packet.request_id in self._response_queues:
            # This shouldn't raise an exception because our queues should be unbounded
            self._response_queues[packet.request_id].put_nowait(packet)
        else:
            log.warning(f"Dropped packet: {packet!r}")

    def _real_write(self, data):
        self._transport.write(data)

    async def _send_packet(self, packet: Packet):
        """
        Send a message. May block due to backpressure.

        Raises BrokenPipeError if unable to send due to closed connection.
        """
        log.debug("send:", packet)
        await self._write_proxy(packet.to_bytes())

    def _open_channel(self):
        """
        Opens a channel defined by request ID.
        Returns a callable (accepting a type and payload to send) and a Queue (where responses go)
        """
        reqid = self._last_request_id + 1
        self._last_request_id = reqid

        q = asyncio.Queue()
        self._response_queues[reqid] = q

        async def send(type, payload):
            packet = Packet(request_id=reqid, type=type, payload=payload)
            await self._send_packet(packet)

        return send, q

    async def login(self, password):
        """
        Authenticate to the server. Should be the first thing done.
        """
        send, q = self._open_channel()
        # Auth failures are sent to reqid -1, so snag that
        self._response_queues[-1] = q

        await send(PacketType.LOGIN, password.encode('utf-8'))

        while True:
            packet = await q.get()
            try:
                if isinstance(packet, Packet):
                    if packet.request_id == -1:
                        raise AuthenticationError(packet.payload.decode('utf-8'))
                    elif packet.type == PacketType.COMMAND:
                        # Successful
                        break
                elif isinstance(packet, Exception):
                    raise AuthenticationError from packet
                elif packet is None:
                    raise Disconnected
                else:
                    raise RuntimeError(repr(packet))
            finally:
                q.task_done()

    async def command(self, cmd):
        """
        Send a command. Generates responses
        """
        send, q = self._open_channel()
        # Auth failures are sent to reqid -1, so snag that
        self._response_queues[-1] = q

        await send(PacketType.COMMAND, cmd.encode('utf-8'))
        await send(100, b"")  # Invalid command

        while True:
            packet = await q.get()
            try:
                if isinstance(packet, Packet):
                    payload = packet.payload
                    if payload == b'Unknown request 64':
                        break
                    else:
                        yield payload.decode('utf-8')
                elif isinstance(packet, Exception):
                    raise packet
                elif packet is None:
                    raise Disconnected
                else:
                    raise RuntimeError(repr(packet))
            finally:
                q.task_done()
