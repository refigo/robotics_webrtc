import asyncio
import logging
import socketio
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
    MediaStreamTrack,
)
from aiortc.contrib.media import MediaPlayer, MediaBlackhole
import av
import fractions
import cv2

# Logging configuration
logging.basicConfig(level=logging.INFO)

# === Basic Settings ===
ROOM = "room1"            # Room name to connect (max 2 people limit on node server)
NICKNAME = "PythonClient" # Client nickname (can be separately sent to server if needed)

class VideoStreamTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, capture):
        super().__init__()
        self.capture = capture
        self.pts = 0

    async def recv(self):
        pts = self.pts
        self.pts += 3000  # 33.33ms per frame at 30fps (3000 units @ 90kHz)

        ret, frame = self.capture.read()
        if not ret:
            raise Exception("Cannot read frame from camera")

        # BGR to RGB conversion
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Convert to av.VideoFrame
        video_frame = av.VideoFrame.from_ndarray(frame, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = fractions.Fraction(1, 90000)  # 90kHz timebase

        return video_frame

    def stop(self):
        if self.capture is not None:
            self.capture.release()

class AudioStreamTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, input_device_index=None):
        super().__init__()
        import sounddevice as sd
        self.stream = sd.InputStream(
            channels=1,
            samplerate=48000,
            dtype='float32',
            device=input_device_index
        )
        self.stream.start()
        self.pts = 0

    async def recv(self):
        pts = self.pts
        self.pts += 960  # 20ms at 48kHz

        # Read audio data
        frame, _ = self.stream.read(960)  # 20ms of audio at 48kHz
        frame = av.AudioFrame.from_ndarray(
            frame,
            format='flt',
            layout='mono',
            # rate=48000
        )
        frame.pts = pts
        frame.time_base = fractions.Fraction(1, 48000)
        return frame

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()

def list_media_devices():
    video_devices = []
    # Search for video devices using OpenCV
    index = 0
    while True:
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            break
        name = f"Video Device {index}"
        video_devices.append({"index": index, "name": name})
        cap.release()
        index += 1

    # Search for audio devices
    audio_devices = []
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                audio_devices.append({
                    "index": i,
                    "name": device['name']
                })
    except Exception as e:
        logging.warning(f"Failed to search audio devices: {e}")

    return video_devices, audio_devices

# Create python-socketio asynchronous client
sio = socketio.AsyncClient()

# Global variables: RTCPeerConnection, data channel, media player
pc = None
data_channel = None
player = None

# ---------------------------
# 1. RTCPeerConnection and media stream setup
# ---------------------------
async def setup_peer_connection():
    """
    Creates RTCPeerConnection and registers ICE event and data channel/track event handlers.
    Searches for available media devices and adds streams.
    """
    global pc, player
    # Basic RTCConfiguration using STUN server
    configuration = RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    )
    pc = RTCPeerConnection(configuration=configuration)
    logging.info("RTCPeerConnection created.")

    # --- Search and add media devices ---
    try:
        video_devices, audio_devices = list_media_devices()
        
        if video_devices:
            # Use first video device
            cap = cv2.VideoCapture(video_devices[0]["index"])
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                video_track = VideoStreamTrack(cap)
                pc.addTrack(video_track)
                logging.info(f"Video track added: {video_devices[0]['name']}")

        if audio_devices:
            # Use first audio device
            audio_track = AudioStreamTrack(audio_devices[0]["index"])
            pc.addTrack(audio_track)
            logging.info(f"Audio track added: {audio_devices[0]['name']}")

        # Check track status
        senders = pc.getSenders()
        for sender in senders:
            logging.info(f"Local track info: kind={sender.track.kind}, id={id(sender.track)}")
    except Exception as e:
        logging.warning(f"Cannot add media stream: {e}")
        logging.info("Using data channel only without media stream")

    # ICE candidate event handler
    @pc.on("icecandidate")
    async def on_icecandidate(event):
        candidate = event.candidate
        if candidate:
            candidate_data = {
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            }
            logging.info("Local ICE candidate generated: %s", candidate_data)
            await sio.emit("ice", (candidate_data, ROOM))

    # Handle when data channel is created by peer
    @pc.on("datachannel")
    def on_datachannel(channel):
        global data_channel
        data_channel = channel
        logging.info("Data channel received: %s", channel.label)

        @data_channel.on("message")
        def on_message(message):
            logging.info("Data channel message received: %s", message)

    # When peer's media stream (track) is added
    @pc.on("track")
    def on_track(track):
        logging.info(f"Track received: kind={track.kind}")
        recorder = MediaBlackhole()
        recorder.addTrack(track)
        asyncio.ensure_future(recorder.start())
        
        @track.on("ended")
        async def on_ended():
            logging.info("Track ended: %s", track.kind)
            await recorder.stop()

    return pc

# ---------------------------
# 2. Socket.IO event handlers
# ---------------------------
@sio.event
async def connect():
    logging.info("Connected to signaling server.")
    logging.info("Requesting to join room '%s'...", ROOM)
    
    async def on_join_complete(*args):
        logging.info("Successfully joined room '%s'", ROOM)
    
    await sio.emit("join_room", ROOM, callback=on_join_complete)

@sio.event
async def disconnect():
    logging.info("Disconnected from signaling server.")

# When server sends "welcome" event after another user joins the room
@sio.on("welcome")
async def on_welcome(user):
    logging.info("'%s' joined and welcome event received.", user)
    global pc, data_channel
    if pc is None:
        await setup_peer_connection()

    # [Offerer] – Create data channel
    data_channel = pc.createDataChannel("chat")
    logging.info("Data channel created (label=%s)", data_channel.label)

    @data_channel.on("message")
    def on_message(message):
        logging.info("Data channel message received: %s", message)

    # Create offer, set local SDP, and send to signaling server
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    offer_data = {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
    logging.info("Offer created and sent: %s", offer_data)
    await sio.emit("offer", (offer_data, ROOM))

# When peer sends offer (Answerer)
@sio.on("offer")
async def on_offer(offer_data):
    logging.info("Offer received: %s", offer_data)
    global pc
    if pc is None:
        await setup_peer_connection()

    # Set remote SDP
    offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
    await pc.setRemoteDescription(offer)

    # Create answer, set local SDP, and send to signaling server
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    answer_data = {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
    logging.info("Answer created and sent: %s", answer_data)
    await sio.emit("answer", (answer_data, ROOM))
    
# When peer sends answer (Offerer)
@sio.on("answer")
async def on_answer(answer_data):
    logging.info("Answer received: %s", answer_data)
    global pc
    answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
    await pc.setRemoteDescription(answer)

# ICE candidate signaling
@sio.on("ice")
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
        await pc.addIceCandidate(candidate)
    except Exception as e:
        logging.error("Error processing ICE candidate: %s", e)

# Other event handlers (e.g., when user leaves the room)
@sio.on("bye")
async def on_bye(user):
    logging.info("'%s' left the room.", user)

# (Optional) New chat message received – corresponds to browser client's "new_message" event
@sio.on("new_message")
async def on_new_message(message):
    logging.info("Chat message received: %s", message)

# (Optional) Room is full
@sio.on("room_full")
async def on_room_full():
    logging.warning("Room is full. Disconnecting.")
    await sio.disconnect()

# ---------------------------
# 3. Main loop: Connect to signaling server
# ---------------------------
async def main():
    # Signaling server URL (Node.js server)
    await sio.connect("http://localhost:3000")
    logging.info("Main loop started. Press Ctrl+C to exit.")
    await sio.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Program exited")
