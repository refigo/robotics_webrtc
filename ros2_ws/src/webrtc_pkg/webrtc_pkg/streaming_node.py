#!/usr/bin/env python3

import asyncio
import logging
import os
import threading
import rclpy
from rclpy.node import Node
import cv_bridge 
from sensor_msgs.msg import Image
import cv2
import time
import numpy as np

from .webrtc import (
    VideoStreamTrack,
    AudioStreamTrack,
    list_media_devices,
    WebRTCHttpServer,
    WebRTCSocketIOClient,
)

# Setting up logging
ROOT = os.path.dirname(__file__)
logger = logging.getLogger("webrtc_streaming")
logging.basicConfig(level=logging.INFO)

class Intermediate(Node):
    """
    ROS Node for handling image data and adjusting the quality based on network conditions.
    """
    def __init__(self, mode="manual"):
        super().__init__('intermediate_node')
        self.bridge = cv_bridge.CvBridge()
        self.image_subscriber = self.create_subscription(Image, '/camera/camera/color/image_raw', self.image_callback, 10)
        self.last_time = time.time()
        self.fps = 30
        self.lock = threading.Lock()
        # self.latest_image = None
        
        # Create a black placeholder image instead of loading from file
        self.placeholder_image = np.zeros((480, 640, 3), dtype=np.uint8)
        
        # Initialize image buffer
        self.new_image = None
        self.image_received = False
        
        self.rtt = None
        # self.manual_resolution = (1920, 1080)
        self.manual_resolution = (640, 480)  # Start with a more reasonable resolution
        self.mode = mode
        logger.info("Intermediate Node initialized in %s mode", self.mode)

    def image_callback(self, msg):
        """
        Callback function to process the incoming image messages.
        """
        current_time = time.time()
        if current_time - self.last_time >= 1.0 / self.fps:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            if self.mode == "manual":
                resized_image = cv2.resize(cv_image, self.manual_resolution)
                self.new_image = resized_image
                # logger.debug("Updated image in manual mode, shape: %s", resized_image.shape)
            else:
                resized_image = self.resize_image(cv_image)
                self.new_image = resized_image
                # logger.debug("Updated image in auto mode, shape: %s", resized_image.shape)
            self.last_time = current_time
        # try:
        #     current_time = time.time()
        #     if current_time - self.last_time >= 1.0 / self.fps:
        #         cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
                
        #         with self.lock:
        #             if self.mode == "manual":
        #                 resized_image = cv2.resize(cv_image, self.manual_resolution)
        #                 self.new_image = resized_image
        #                 logger.debug("Updated image in manual mode, shape: %s", resized_image.shape)
        #             else:
        #                 resized_image = self.resize_image(cv_image)
        #                 self.new_image = resized_image
        #                 logger.debug("Updated image in auto mode, shape: %s", resized_image.shape)
                    
        #             self.image_received = True
        #             self.last_time = current_time
                    
        # except Exception as e:
        #     logger.error("Error in image_callback: %s", e)


    def update_bandwidth(self, msg):
        """
        Updates the available bandwidth based on message data.
        """
        self.bandwidth = msg.data
        self.adjust_fps_and_resolution()

    def adjust_fps_and_resolution(self):
        """
        Adjusts FPS and resolution based on the current round-trip time (RTT).
        """
        rtt_settings = {
            (0, 3): {'resolution': (1920, 1080), 'fps': 60},
            (4, 7): {'resolution': (820, 720), 'fps': 30},
            (8, 11): {'resolution': (640, 480), 'fps': 15},
            (12, float('inf')): {'resolution': (320, 240), 'fps': 5},
        }
        for (lower_bound, upper_bound), settings in rtt_settings.items():
            if lower_bound <= self.rtt < upper_bound:
                self.fps = settings['fps']
                self.resolution = settings['resolution']
                logger.info("Adjusted FPS to %s and resolution to %s", self.fps, self.resolution)
                break

    def resize_image(self, image):
        """
        Resize the image based on the current bandwidth.
        """
        if self.rtt is not None:
            self.adjust_fps_and_resolution()
            return cv2.resize(image, self.resolution)
        return image

    def get_latest_image(self):
        """
        Returns the latest processed image or a placeholder if none available.
        """
        if self.new_image is not None:
            logger.debug("Returning latest image, shape: %s", self.new_image.shape)
            return self.new_image
        logger.debug("No image available, returning placeholder")
        return self.placeholder_image
        # with self.lock:
        #     if self.image_received and self.new_image is not None:
        #         logger.debug("Returning latest image, shape: %s", self.new_image.shape)
        #         return self.new_image
            
        #     logger.debug("No image available, returning placeholder")
        #     return self.placeholder_image

class WebRTCStreamingNode(Node):
    """
    Main ROS2 node that integrates HTTP server and Socket.IO client for WebRTC streaming
    """
    def __init__(self):
        super().__init__('webrtc_streaming_node')
        
        # Initialize the intermediate node for image processing
        self.intermediate = Intermediate()
        
        # Initialize HTTP server
        self.http_server = WebRTCHttpServer(ROOT, self.intermediate)
        
        # Initialize Socket.IO client
        self.socketio_client = WebRTCSocketIOClient(self.intermediate)
        
        logger.info("WebRTC Streaming Node initialized")

    async def start(self):
        """
        Start both HTTP server and Socket.IO client
        """
        # Start HTTP server
        await self.http_server.start()
        
        # Try to connect to signaling server, but don't fail if it's not available
        try:
            await self.socketio_client.connect()
            logger.info("Connected to signaling server")
        except Exception as e:
            logger.warning(f"Could not connect to signaling server: {e}")
            logger.info("Continuing with HTTP server only")
        
        logger.info("WebRTC Streaming Node started")

    async def stop(self):
        """
        Stop both HTTP server and Socket.IO client
        """
        tasks = [self.http_server.stop()]
        if self.socketio_client.sio.connected:
            tasks.append(self.socketio_client.disconnect())
        
        await asyncio.gather(*tasks)
        logger.info("WebRTC Streaming Node stopped")

def main(args=None):
    """
    Main entry point for the ROS2 node
    """
    rclpy.init(args=args)
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()

async def async_main(args=None):
    """
    Asynchronous main function
    """
    # Create and initialize the streaming node
    node = WebRTCStreamingNode()
    
    # Run ROS2 node in a separate thread
    executor = rclpy.executors.MultiThreadedExecutor()
    executor.add_node(node)
    executor.add_node(node.intermediate) # Good
    
    # Run ROS2 executor in a separate thread
    executor_thread = threading.Thread(target=executor.spin)
    executor_thread.start()
    
    try:
        # Start the streaming node
        await node.start()
        
        # Keep the program running
        try:
            await asyncio.gather(
                node.socketio_client.sio.wait(),
                asyncio.Event().wait()  # This will never complete
            )
        except asyncio.CancelledError:
            pass
            
    finally:
        # Cleanup
        await node.stop()
        executor.shutdown()
        executor_thread.join()

if __name__ == "__main__":
    main()
