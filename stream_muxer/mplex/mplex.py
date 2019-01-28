import asyncio
from .utils import encode_uvarint, decode_uvarint_from_stream
from .mplex_stream import MplexStream
from ..muxed_connection_interface import IMuxedConn


class Mplex(IMuxedConn):
    # pylint: disable=too-many-instance-attributes
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
    """

    def __init__(self, conn):
        """
        create a new muxed connection
        :param conn: an instance of raw connection
        :param initiator: boolean to prevent multiplex with self
        """
        print("fff mplex init")
        self.raw_conn = conn
        self.initiator = conn.initiator

        # Mapping from stream ID -> buffer of messages for that stream
        self.buffers = {}

        self.stream_queue = asyncio.Queue()
        self.data_buffer = bytearray()

        # The initiator of the raw connection need not read upon construction time.
        # It should read when the user decides that it wants to read from the constructed stream.
        if not self.initiator:
            asyncio.ensure_future(self.handle_incoming(None))

    def close(self):
        """
        close the stream muxer and underlying raw connection
        """
        print("fff mplex close")
        self.raw_conn.close()

    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """

    async def read_buffer(self, stream_id):
        """
        Read a message from stream_id's buffer, check raw connection for new messages
        :param stream_id: stream id of stream to read from
        :return: message read
        """
        # Empty buffer or nonexistent stream
        # TODO: propagate up timeout exception and catch
        print("fff mplex read_buffer")
        if stream_id not in self.buffers or self.buffers[stream_id].empty():
            await self.handle_incoming(stream_id)
        if stream_id in self.buffers:
            return await self._read_buffer_exists(stream_id)

        return None

    async def _read_buffer_exists(self, stream_id):
        """
        Reads from raw connection with the assumption that the message buffer for stream_id exsits
        :param stream_id: stream id of stream to read from
        :return: message read
        """
        print("fff mplex _read_buffer_exists")
        try:
            print("fff mplex _read_buffer_exists entered try")
            data = await asyncio.wait_for(self.buffers[stream_id].get(), timeout=5)
            print("fff mplex _read_buffer_exists obtained data")
            # for aspyn
            print("msg: " + str(data) + " read from buffer " + str(stream_id))
            return data
        except asyncio.TimeoutError:
            print("fff mplex _read_buffer_exists timeout error")
            return None

    async def open_stream(self, protocol_id, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :param protocol_id: protocol_id of stream
        :param stream_id: stream_id of stream
        :param peer_id: peer_id that stream connects to
        :param multi_addr: multi_addr that stream connects to
        :return: a new stream
        """
        print("fff mplex open_stream")
        stream_id = self.raw_conn.next_stream_id()
        stream = MplexStream(stream_id, multi_addr, self)
        self.buffers[stream_id] = asyncio.Queue()
        return stream

    async def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        # TODO update to pull out protocol_id from message
        print("fff mplex accept_stream")
        protocol_id = "/echo/1.0.0"
        stream_id = await self.stream_queue.get()
        stream = MplexStream(stream_id, False, self)
        return stream, stream_id, protocol_id

    async def send_message(self, flag, data, stream_id):
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        :return: True if success
        """
        # << by 3, then or with flag
        print("fff mplex send_message| data: " + str(data))
        header = (stream_id << 3) | flag
        header = encode_uvarint(header)

        if data is None:
            data_length = encode_uvarint(0)
            _bytes = header + data_length
        else:
            data_length = encode_uvarint(len(data))
            _bytes = header + data_length + data

        return await self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes):
        """
        writes a byte array to a raw connection
        :param _bytes: byte array to write
        :return: length written
        """
        print("fff mplex write_to_stream")
        self.raw_conn.writer.write(_bytes)
        await self.raw_conn.writer.drain()
        return len(_bytes)

    async def handle_incoming(self, my_stream_id):
        """
        Read a message off of the raw connection and add it to the corresponding message buffer
        """
        # TODO Deal with other types of messages using flag (currently _)
        # TODO call read_message in loop to handle case message for other stream was in conn

        print("fff mplex handle_incoming| my_stream_id: " + str(my_stream_id))
        flag = True
        i = 0
        while flag:
            i += 1
            print("fff mplex calling read_message")
            stream_id, _, message = await self.read_message()
            flag = stream_id is not None and stream_id != my_stream_id and my_stream_id is not None
            print("fff mplex handle_incoming in while| id: " + str(stream_id) + ", msg: " + str(message) + ", my_stream_id:" + str(my_stream_id))

            # for aspyn
            print("read: " + str(message) + " for " + str(stream_id) + " from raw conn")
            if stream_id not in self.buffers:
                self.buffers[stream_id] = asyncio.Queue()
                await self.stream_queue.put(stream_id)

            await self.buffers[stream_id].put(message)
            # for aspyn
            print("put msg: " + str(message) + " for " + str(stream_id) + " in buffer")
            print(str(stream_id) + " buffer size: " + str(self.buffers[stream_id].qsize()))
        print("fff mplex handle_incoming exit")
    async def read_chunk(self):
        """
        Read a chunk of bytes off of the raw connection into data_buffer
        """
        # unused now but possibly useful in the future
        print("fff mplex read_chunk")
        try:
            chunk = await asyncio.wait_for(self.raw_conn.reader.read(-1), timeout=5)
            self.data_buffer += chunk
        except asyncio.TimeoutError:
            print('timeout!')
            return

    async def read_message(self):
        """
        Read a single message off of the raw connection
        :return: stream_id, flag, message contents
        """
        print("fff mplex read_message")
        timeout = .1
        try:
            header = await decode_uvarint_from_stream(self.raw_conn.reader, timeout)
            length = await decode_uvarint_from_stream(self.raw_conn.reader, timeout)
            message = await asyncio.wait_for(self.raw_conn.reader.read(length), timeout=timeout)
        except asyncio.TimeoutError:
            return None, None, None

        flag = header & 0x07
        stream_id = header >> 3

        return stream_id, flag, message
