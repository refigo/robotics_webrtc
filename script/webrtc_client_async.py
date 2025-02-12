import asyncio
import logging
import socketio
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
    RTCIceServer,
)
from aiortc.contrib.media import MediaPlayer, MediaBlackhole
import pyrealsense2 as rs
import numpy as np
import av
import fractions

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# === 기본 설정 ===
ROOM = "room1"            # 접속할 방 이름 (노드 서버에서 최대 2명 제한)
NICKNAME = "PythonClient" # 클라이언트 별칭 (필요에 따라 서버에 별도 전달 가능)

class RealSenseStreamTrack:
    def __init__(self):
        self.kind = "video"
        self.pipeline = None
        self.config = None
        self._start()
        
    def _start(self):
        try:
            # RealSense 파이프라인 설정
            self.pipeline = rs.pipeline()
            self.config = rs.config()
            
            # 사용 가능한 장치 찾기
            ctx = rs.context()
            devices = ctx.query_devices()
            if len(devices) == 0:
                raise Exception("RealSense 장치를 찾을 수 없습니다.")
            
            # 첫 번째 발견된 장치 사용
            device = devices[0]
            logging.info(f"RealSense 장치 발견: {device.get_info(rs.camera_info.name)}")
            
            # RGB 스트림 활성화 (1280x720 @ 30fps)
            self.config.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, 30)
            self.pipeline.start(self.config)
            logging.info("RealSense 스트리밍 시작됨")
            
        except Exception as e:
            logging.error(f"RealSense 초기화 실패: {e}")
            if self.pipeline:
                self.pipeline.stop()
            raise
    
    async def recv(self):
        pts = 0  # Presentation timestamp
        frame_count = 0
        try:
            # 프레임 가져오기
            frames = self.pipeline.wait_for_frames()
            color_frame = frames.get_color_frame()
            
            if not color_frame:
                raise Exception("컬러 프레임을 가져올 수 없습니다.")
            
            # numpy 배열로 변환
            image = np.asanyarray(color_frame.get_data())
            
            # BGR에서 RGB로 변환
            image = image[..., ::-1]
            
            # av.VideoFrame로 변환
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            
            # 타임스탬프와 시간 설정
            pts += 3000  # 30fps에서 각 프레임은 33.33ms (3000 units @ 90kHz)
            frame.pts = pts
            frame.time_base = fractions.Fraction(1, 90000)  # 90kHz timebase
            
            frame_count += 1
            if frame_count % 30 == 0:  # 매 30프레임마다 로그
                logging.info(f"비디오 프레임 전송 중... (frame #{frame_count})")
            
            return frame
            
        except Exception as e:
            logging.error(f"프레임 수신 중 오류: {e}")
            raise
    
    def stop(self):
        if self.pipeline:
            self.pipeline.stop()
            logging.info("RealSense 스트리밍 중지됨")

# python-socketio의 비동기 클라이언트 생성
sio = socketio.AsyncClient()

# 전역 변수: RTCPeerConnection, 데이터 채널, 미디어 플레이어
pc = None
data_channel = None
player = None

# ---------------------------
# 1. RTCPeerConnection 및 미디어 스트림 설정
# ---------------------------
async def setup_peer_connection():
    """
    RTCPeerConnection을 생성하고, ICE 이벤트 및 데이터 채널/트랙 이벤트 핸들러를 등록한다.
    가능한 경우 RealSense 카메라 스트림을 추가한다.
    """
    global pc, player
    # STUN 서버를 이용한 기본 RTCConfiguration
    configuration = RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    )
    pc = RTCPeerConnection(configuration=configuration)
    logging.info("RTCPeerConnection 생성됨.")

    # --- RealSense 스트림 추가 ---
    try:
        # RealSense 트랙 생성 및 추가
        realsense_track = RealSenseStreamTrack()
        pc.addTrack(realsense_track)
        logging.info("RealSense 비디오 트랙이 추가됨")
        
        # 트랙 상태 확인
        senders = pc.getSenders()
        for sender in senders:
            logging.info(f"로컬 트랙 정보: kind={sender.track.kind}, id={id(sender.track)}")
    except Exception as e:
        logging.warning(f"RealSense 스트림을 추가할 수 없습니다: {e}")
        logging.info("비디오 스트림 없이 데이터 채널만 사용합니다.")

    # ICE candidate 발생시 이벤트 핸들러
    @pc.on("icecandidate")
    async def on_icecandidate(event):
        candidate = event.candidate
        if candidate:
            candidate_data = {
                "candidate": candidate.candidate,
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            }
            logging.info("로컬 ICE candidate 발생: %s", candidate_data)
            await sio.emit("ice", (candidate_data, ROOM))

    # 상대측에서 데이터 채널이 생성되었을 경우 처리
    @pc.on("datachannel")
    def on_datachannel(channel):
        global data_channel
        data_channel = channel
        logging.info("데이터 채널 수신됨: %s", channel.label)

        @data_channel.on("message")
        def on_message(message):
            logging.info("데이터 채널 메시지 수신: %s", message)

    # 상대측의 미디어 스트림(트랙)이 추가될 경우
    @pc.on("track")
    def on_track(track):
        logging.info(f"트랙 수신됨: kind={track.kind}")
        recorder = MediaBlackhole()
        recorder.addTrack(track)
        asyncio.ensure_future(recorder.start())
        
        @track.on("ended")
        async def on_ended():
            logging.info("트랙 종료됨: %s", track.kind)
            await recorder.stop()

    return pc

# ---------------------------
# 2. Socket.IO 이벤트 핸들러
# ---------------------------
@sio.event
async def connect():
    logging.info("시그널링 서버에 연결됨.")
    logging.info("방 '%s' 에 입장 요청...", ROOM)
    
    async def on_join_complete(*args):
        logging.info("방 '%s' 에 성공적으로 입장함", ROOM)
    
    await sio.emit("join_room", ROOM, callback=on_join_complete)

@sio.event
async def disconnect():
    logging.info("시그널링 서버와의 연결이 끊어짐.")

# 방에 입장한 다른 사용자가 있을 경우 서버에서 "welcome" 이벤트가 발생함
@sio.on("welcome")
async def on_welcome(user):
    logging.info("'%s' 가 입장하여 welcome 이벤트 수신됨.", user)
    global pc, data_channel
    if pc is None:
        await setup_peer_connection()

    # [Offerer] – 주도측에서는 데이터 채널을 직접 생성
    data_channel = pc.createDataChannel("chat")
    logging.info("데이터 채널 생성됨 (label=%s)", data_channel.label)

    @data_channel.on("message")
    def on_message(message):
        logging.info("데이터 채널 메시지 수신: %s", message)

    # offer 생성, 로컬 SDP 설정 후 시그널링 서버로 전송
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    offer_data = {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
    logging.info("Offer 생성 후 전송: %s", offer_data)
    await sio.emit("offer", (offer_data, ROOM))

# 상대방이 offer를 보낸 경우 (Answerer)
@sio.on("offer")
async def on_offer(offer_data):
    logging.info("Offer 수신: %s", offer_data)
    global pc
    if pc is None:
        await setup_peer_connection()

    # 원격 SDP 설정
    offer = RTCSessionDescription(sdp=offer_data["sdp"], type=offer_data["type"])
    await pc.setRemoteDescription(offer)

    # answer 생성, 로컬 SDP 설정 후 전송
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)
    answer_data = {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}
    logging.info("Answer 생성 후 전송: %s", answer_data)
    await sio.emit("answer", (answer_data, ROOM))
    
# 상대방이 answer를 보낸 경우 (Offerer)
@sio.on("answer")
async def on_answer(answer_data):
    logging.info("Answer 수신: %s", answer_data)
    global pc
    answer = RTCSessionDescription(sdp=answer_data["sdp"], type=answer_data["type"])
    await pc.setRemoteDescription(answer)

# ICE candidate 시그널링 처리
@sio.on("ice")
async def on_ice(ice_data):
    if ice_data is None:
        logging.info("ICE gathering 완료 (null candidate)")
        return
        
    try:
        logging.info("원격 ICE candidate 수신: %s", ice_data)
        # aiortc의 RTCIceCandidate는 인자 이름이 다름 (candidate -> sdpMid, sdpMLineIndex, foundation 등)
        candidate_str = ice_data.get("candidate", "")
        if not candidate_str:
            return
            
        # candidate 문자열에서 필요한 정보 추출
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
        logging.error("ICE candidate 처리 중 오류 발생: %s", e)

# 기타 이벤트 처리 (예: 사용자가 방을 떠날 경우)
@sio.on("bye")
async def on_bye(user):
    logging.info("'%s' 가 방을 떠남.", user)

# (선택사항) 새로운 채팅 메시지 수신 – 브라우저 클라이언트의 "new_message" 이벤트와 대응
@sio.on("new_message")
async def on_new_message(message):
    logging.info("채팅 메시지 수신: %s", message)

# (선택사항) 방이 꽉 찼을 경우 처리
@sio.on("room_full")
async def on_room_full():
    logging.warning("방이 꽉 찼습니다. 연결을 종료합니다.")
    await sio.disconnect()

# ---------------------------
# 3. 메인 루프: 시그널링 서버에 연결
# ---------------------------
async def main():
    # 시그널링 서버 주소 (Node.js 서버)
    await sio.connect("http://localhost:3000")
    logging.info("메인 루프 시작. Ctrl+C 로 종료 가능.")
    await sio.wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("프로그램 종료")
