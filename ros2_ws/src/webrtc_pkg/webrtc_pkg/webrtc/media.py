#!/usr/bin/env python3

import cv2
import logging
import fractions
import av
from aiortc import MediaStreamTrack

logger = logging.getLogger(__name__)

class VideoStreamTrack(MediaStreamTrack):
    """
    MediaStreamTrack for video streaming from ROS Image messages
    """
    kind = "video"

    def __init__(self, intermediate_node):
        super().__init__()
        self.intermediate = intermediate_node
        self.start_time = 0
        self.frames = 0
        self.framerate = 30

    async def next_timestamp(self):
        """
        Calculate the timestamp for the next frame
        """
        self.frames += 1
        next_time = self.start_time + (self.frames / self.framerate)
        return int(next_time * 1000)

    async def recv(self):
        """
        Receive the next video frame
        """
        frame = self.intermediate.get_latest_image()
        pts = await self.next_timestamp()
        
        # Convert BGR to RGB and create VideoFrame
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = av.VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = fractions.Fraction(1, 1000)
        
        # logger.debug("Sending video frame, shape: %s", frame.shape)
        return video_frame

class AudioStreamTrack(MediaStreamTrack):
    """
    MediaStreamTrack for audio streaming
    """
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

        frame, _ = self.stream.read(960)  # 20ms of audio at 48kHz
        frame = av.AudioFrame.from_ndarray(
            frame,
            format='flt',
            layout='mono'
        )
        frame.pts = pts
        frame.time_base = fractions.Fraction(1, 48000)
        return frame

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()

def list_media_devices():
    """
    List available video and audio devices
    """
    video_devices = []
    index = 0
    while True:
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            break
        name = f"Video Device {index}"
        video_devices.append({"index": index, "name": name})
        cap.release()
        index += 1

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
        logger.warning(f"Failed to search audio devices: {e}")

    return video_devices, audio_devices
