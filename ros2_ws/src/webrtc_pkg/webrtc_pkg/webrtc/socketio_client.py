#!/usr/bin/env python3

import logging
import socketio
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
)
from .media import VideoStreamTrack, AudioStreamTrack, list_media_devices

logger = logging.getLogger(__name__)

class WebRTCSocketIOClient:
    """
    Socket.IO client for WebRTC peer connections via signaling server
    """
    def __init__(self, intermediate_node, room="room1", nickname="ROS2Client"):
        self.intermediate = intermediate_node
        self.room = room
        self.nickname = nickname
        self.sio = socketio.AsyncClient()
        self.pc = None
        self.setup_handlers()

    def setup_handlers(self):
        """
        Set up Socket.IO event handlers
        """
        @self.sio.event
        async def connect():
            logger.info("Connected to signaling server")

            async def on_join_complete(*args):
                logging.info("Successfully joined room '%s'", self.room)

            # TODO: use later after server development: {"room": self.room, "nickname": self.nickname}
            await self.sio.emit("join_room", self.room, callback=on_join_complete)

        @self.sio.event
        async def disconnect():
            logger.info("Disconnected from signaling server")
            if self.pc:
                await self.pc.close()
                self.pc = None

        @self.sio.on("welcome")
        async def on_welcome(user):
            logger.info(f"User {user} joined the room")
            if self.pc is None:
                await self.setup_peer_connection()
                offer = await self.pc.createOffer()
                await self.pc.setLocalDescription(offer)
                await self.sio.emit("offer", ({"sdp": offer.sdp, "type": offer.type}, self.room))

        @self.sio.on("offer")
        async def on_offer(offer_data):
            if self.pc is None:
                await self.setup_peer_connection()
            offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
            await self.pc.setRemoteDescription(offer)
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            await self.sio.emit("answer", ({"sdp": answer.sdp, "type": answer.type}, self.room))

        @self.sio.on("answer")
        async def on_answer(answer_data):
            if self.pc:
                answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
                await self.pc.setRemoteDescription(answer)

        @self.sio.on("ice")
        async def on_ice(ice_data):
            if ice_data and self.pc:
                candidate = RTCIceCandidate(
                    sdpMid=ice_data["sdpMid"],
                    sdpMLineIndex=ice_data["sdpMLineIndex"],
                    candidate=ice_data["candidate"],
                )
                await self.pc.addIceCandidate(candidate)

    async def setup_peer_connection(self):
        """
        Set up WebRTC peer connection
        """
        configuration = RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
        self.pc = RTCPeerConnection(configuration=configuration)
        
        # Add video track
        video_track = VideoStreamTrack(self.intermediate)
        self.pc.addTrack(video_track)
        
        # Add audio track if available
        # try:
        #     _, audio_devices = list_media_devices()
        #     if audio_devices:
        #         audio_track = AudioStreamTrack(audio_devices[0]["index"])
        #         self.pc.addTrack(audio_track)
        #         logger.info(f"Audio track added: {audio_devices[0]['name']}")
        # except Exception as e:
        #     logger.warning(f"Cannot add audio track: {e}")

        @self.pc.on("icecandidate")
        async def on_icecandidate(event):
            if event.candidate:
                candidate_data = {
                    "candidate": event.candidate.candidate,
                    "sdpMid": event.candidate.sdpMid,
                    "sdpMLineIndex": event.candidate.sdpMLineIndex,
                }
                await self.sio.emit("ice", (candidate_data, self.room))

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", self.pc.connectionState)
            if self.pc.connectionState == "failed":
                await self.pc.close()
                self.pc = None

    async def connect(self, server_url='http://localhost:3000'):
        """
        Connect to the signaling server
        """
        await self.sio.connect(server_url)

    async def disconnect(self):
        """
        Disconnect from the signaling server and cleanup
        """
        if self.pc:
            await self.pc.close()
            self.pc = None
        if self.sio.connected:
            await self.sio.disconnect()
