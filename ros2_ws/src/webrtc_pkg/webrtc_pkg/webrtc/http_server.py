#!/usr/bin/env python3

import os
import json
import uuid
import logging
import asyncio
from aiohttp import web
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
    RTCIceServer,
)

from .media import VideoStreamTrack, AudioStreamTrack, list_media_devices

logger = logging.getLogger(__name__)

class WebRTCHttpServer:
    """
    HTTP server for WebRTC peer connections
    """
    def __init__(self, root_path, intermediate_node):
        self.root = root_path
        self.intermediate = intermediate_node
        self.pcs = set()
        self.app = None
        self.runner = None
        self.site = None
        
        # Configure ICE servers
        self.ice_servers = [
            RTCIceServer(urls=[
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
                "stun:stun2.l.google.com:19302",
                "stun:stun3.l.google.com:19302",
                "stun:stun4.l.google.com:19302",
            ]),
        ]

    def setup_routes(self):
        """
        Set up HTTP server routes
        """
        self.app = web.Application()
        self.app.on_shutdown.append(self.on_shutdown)
        self.app.router.add_get("/", self.index)
        # self.app.router.add_get("/index2", self.index2)
        self.app.router.add_get("/client.js", self.javascript)
        self.app.router.add_post("/offer", self.handle_offer)

    async def start(self, host='0.0.0.0', port=8081):
        """
        Start the HTTP server
        """
        self.setup_routes()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, host, port)
        await self.site.start()
        logger.info(f"HTTP server started at http://{host}:{port}")

    async def stop(self):
        """
        Stop the HTTP server
        """
        coros = [pc.close() for pc in self.pcs]
        await asyncio.gather(*coros)
        self.pcs.clear()
        
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

    async def index(self, request):
        """
        Serve the index.html page
        """
        content = open(os.path.join(self.root, "index.html"), "r").read()
        return web.Response(content_type="text/html", text=content)

    async def index2(self, request):
        """
        Serve the index2.html page
        """
        content = open(os.path.join(self.root, "index2.html"), "r").read()
        return web.Response(content_type="text/html", text=content)

    async def javascript(self, request):
        """
        Serve the client.js file
        """
        content = open(os.path.join(self.root, "client.js"), "r").read()
        return web.Response(content_type="application/javascript", text=content)

    async def handle_offer(self, request):
        """
        Handle WebRTC offer from HTTP client
        """
        params = await request.json()
        offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
        client_resolutions = params.get("video_resolution", "1280x720")

        if self.intermediate.mode == "manual":
            shape = client_resolutions.split('x')
            new_resolution = (int(shape[0]), int(shape[1]))
            self.intermediate.manual_resolution = new_resolution

        pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=self.ice_servers))
        pc_id = f"HTTPPeerConnection({uuid.uuid4()})"
        self.pcs.add(pc)

        def log_info(msg, *args):
            logger.info(pc_id + " " + msg, *args)

        log_info("Received WebRTC offer via HTTP")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            log_info("Connection state is %s", pc.connectionState)
            if pc.connectionState == "failed":
                await pc.close()
                self.pcs.discard(pc)

        # Add tracks
        video_track = VideoStreamTrack(self.intermediate)
        pc.addTrack(video_track)

        try:
            _, audio_devices = list_media_devices()
            if audio_devices:
                audio_track = AudioStreamTrack(audio_devices[0]["index"])
                pc.addTrack(audio_track)
                log_info(f"Audio track added: {audio_devices[0]['name']}")
        except Exception as e:
            logger.warning(f"Cannot add audio track: {e}")

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return web.Response(
            content_type="application/json",
            text=json.dumps({
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            }),
        )

    async def on_shutdown(self, app):
        """
        Clean up resources on shutdown
        """
        await self.stop()
