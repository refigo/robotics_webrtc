#!/usr/bin/env python3

import logging
import socketio
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceServer,
    RTCIceGatherer,
    RTCIceTransport,
    RTCDtlsTransport,
    RTCConfiguration,
    RTCIceCandidate
)
from .media import VideoStreamTrack, AudioStreamTrack, list_media_devices
import asyncio


# debug mode
# logging.basicConfig(level=logging.DEBUG)
# logging.getLogger('aioice').setLevel(logging.DEBUG)
# logging.getLogger('aiortc').setLevel(logging. DEBUG)

logger = logging.getLogger(__name__)

class WebRTCSocketIOClient:
    """
    Socket.IO client for WebRTC peer connections via signaling server
    """
    def __init__(self, intermediate_node, room="room2", nickname="ROS2Client"):
        self.intermediate = intermediate_node
        self.room = room
        self.nickname = nickname
        self.sio = socketio.AsyncClient()
        self.pc = None
        
        # Configure ICE servers
        self.ice_servers = [
            RTCIceServer(urls=[
                "stun:3.34.132.103:3478",
                # "turn:3.34.132.103:3478?transport=udp",
                # "turn:3.34.132.103:3478?transport=tcp",
                # "turn:3.34.132.103:3478?transport=tls"
            ]),
            RTCIceServer(urls=[
                "turn:3.34.132.103:3478?transport=udp",
                # "turn:3.34.132.103:3478?transport=tcp",
                # "turn:3.34.132.103:3478?transport=tls"
            ], username="testref", credential="Ref32111!"),
            # RTCIceServer(urls="stun:stun.l.google.com:19302"),
            # RTCIceServer(urls="stun:stun1.l.google.com:19302"),
            # RTCIceServer(urls="stun:stun2.l.google.com:19302"),
            # RTCIceServer(urls="stun:stun3.l.google.com:19302"),
            # RTCIceServer(urls="stun:stun4.l.google.com:19302"),
            # RTCIceServer(urls=[
            #     "stun:stun.l.google.com:19302",
            #     "stun:stun1.l.google.com:19302",
            #     "stun:stun2.l.google.com:19302",
            #     "stun:stun3.l.google.com:19302",
            #     "stun:stun4.l.google.com:19302",
            # ]),
        ]
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
                await self.create_and_send_offer()

        @self.sio.on("offer")
        async def on_offer(offer_data):
            if self.pc is None:
                await self.setup_peer_connection()
            offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
            await self.pc.setRemoteDescription(offer)
            answer = await self.pc.createAnswer()
            print(f'answer: {answer}')
            await self.pc.setLocalDescription(answer)
            logging.info("Answer created and sent: %s", {"sdp": answer.sdp, "type": answer.type})
            await self.sio.emit("answer", ({"sdp": answer.sdp, "type": answer.type}, self.room))
            # await self.handle_offer(offer_data)

        @self.sio.on("answer")
        async def on_answer(answer_data):
            if self.pc:
                await self.handle_answer(answer_data)

        @self.sio.on("ice")
        async def on_ice(ice_data):
            if ice_data is None:
                logging.info("ICE gathering complete (null candidate)")
                return
                
            try:
                logging.info("Remote ICE candidate received: %s", ice_data)
                # aiortc's RTCIceCandidate has different argument names (candidate -> sdpMid, sdpMLineIndex, foundation, etc.)
                candidate_str = ice_data.get("candidate", "")
                if not candidate_str:
                    return
                    
                # Extract necessary information from candidate string
                parts = candidate_str.split()
                foundation = parts[0].split(":")[1]
                component = int(parts[1])
                protocol = parts[2]
                priority = int(parts[3])
                ip = parts[4]
                port = int(parts[5])
                type = parts[7]
                
                candidate = RTCIceCandidate(
                    foundation=foundation,
                    component=component,
                    protocol=protocol,
                    priority=priority,
                    ip=ip,
                    port=port,
                    type=type,
                    sdpMid=ice_data.get("sdpMid"),
                    sdpMLineIndex=ice_data.get("sdpMLineIndex")
                )
                await self.pc.addIceCandidate(candidate)
            except Exception as e:
                logging.error("Error processing ICE candidate: %s", e)

    async def setup_peer_connection(self):
        """Setup WebRTC peer connection"""
        logger.info("Setting up new peer connection")
        if self.pc:
            logger.warning("Peer connection already exists")
            return

        # Create peer connection with gathered candidates
        config = RTCConfiguration(
            iceServers=self.ice_servers,
        )
        self.pc = RTCPeerConnection(configuration=config)
        logger.info("Created new RTCPeerConnection")

        @self.pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", self.pc.connectionState)
            if self.pc.connectionState == "closed" or self.pc.connectionState == "failed":
                logger.info("Closing peer connection")
                await self.pc.close()
                self.pc = None

        @self.pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            logger.info("ICE gathering state is %s", self.pc.iceGatheringState)
            if self.pc.iceGatheringState == "complete" and self.pc.localDescription:
                logger.info("ICE gathering complete")

        # Add video track
        video_track = VideoStreamTrack(self.intermediate)
        self.pc.addTrack(video_track)
        logger.info("Added video track to peer connection")

        # Create ICE gatherer first
        self.ice_gatherer = RTCIceGatherer(iceServers=self.ice_servers)
        logger.info("Created ICE gatherer")

        # Start gathering candidates
        await self.ice_gatherer.gather()
        await asyncio.sleep(1)
        
        # Get local candidates and parameters
        local_candidates = self.ice_gatherer.getLocalCandidates()
        local_parameters = self.ice_gatherer.getLocalParameters()
        
        # Log all gathered candidates
        for candidate in local_candidates:
            candidate_str = str(candidate)
            logger.info("Raw ICE candidate: %s", candidate_str)
            
            # Parse candidate string into proper format
            # Example format: "candidate:1467250027 1 udp 2122260223 192.168.0.196 56143 typ host"
            components = {}
            for attr in candidate_str.split(','):
                key, value = attr.split('=')
                components[key.strip()] = value.strip("'")
            
            # Create properly formatted candidate string
            formatted_candidate = f"candidate:{components.get('foundation', '0')} " \
                                f"{components.get('component', '1')} " \
                                f"{components.get('protocol', 'udp')} " \
                                f"{components.get('priority', '0')} " \
                                f"{components.get('ip', '')} " \
                                f"{components.get('port', '0')} " \
                                f"typ {components.get('type', 'host')}"

            # Add related address if present
            if components.get('relatedAddress'):
                formatted_candidate += f" raddr {components['relatedAddress']} rport {components.get('relatedPort', '0')}"
            
            logger.info("Formatted ICE candidate: %s", formatted_candidate)
            
            # Log candidate type
            if components.get('type') == 'srflx':
                logger.info("STUN discovered public IP: %s", components.get('ip'))
            elif components.get('type') == 'host':
                logger.info("Local candidate: %s", components.get('ip'))
            elif components.get('type') == 'relay':
                logger.info("Relay candidate: %s", components.get('ip'))
            
            # Send properly formatted candidate to peer
            candidate_dict = {
                "candidate": formatted_candidate,
                "sdpMid": "0",
                "sdpMLineIndex": 0,
            }
            await self.sio.emit("ice", (candidate_dict, self.room))
            logger.info("Sent ICE candidate to signaling server")


    async def create_and_send_offer(self):
        """Create and send offer"""
        logger.info("Creating offer")
        offer = await self.pc.createOffer()
        logger.info("Setting local description (offer)")
        await self.pc.setLocalDescription(offer)
        logger.info("Offer created and set as local description")
        
        # Wait a bit for initial candidates to be gathered
        # while self.pc.iceGatheringState == "new":
        #     await asyncio.sleep(0.1)
        
        await self.sio.emit("offer", ({
            "sdp": self.pc.localDescription.sdp, # offer.sdp
            "type": self.pc.localDescription.type # offer.type
        }, self.room))
        logger.info("Offer created and sent: %s", {"sdp": offer.sdp, "type": offer.type})
        # logger.info("Offer sent to signaling server")

    async def handle_offer(self, offer_data):
        """Handle incoming offer"""
        logger.info("Handling incoming offer")
        if self.pc is None:
            await self.setup_peer_connection()
            
        offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
        logger.info("Setting remote description (offer)")
        await self.pc.setRemoteDescription(offer)
        
        # Before make anser, stay ice gathering state "complete"
        while self.pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)
        logger.info("Creating answer")
        answer = await self.pc.createAnswer()
        logger.info("Setting local description (answer)")
        await self.pc.setLocalDescription(answer)
        
        # Wait a bit for initial candidates to be gathered
        # while self.pc.iceGatheringState == "new":
        #     await asyncio.sleep(0.1)
            
        await self.sio.emit("answer", ({
            "sdp": answer.sdp,
            "type": answer.type
        }, self.room))
        logger.info("Answer sent to signaling server")

    async def handle_answer(self, answer_data):
        """Handle incoming answer"""
        if self.pc:
            answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
            logger.info("Setting remote description (answer)")
            await self.pc.setRemoteDescription(answer)

    async def connect(self, server_url='http://localhost:3000'):
        """
        Connect to the signaling server
        """
        server_url = 'http://3.34.45.27:3000'
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
