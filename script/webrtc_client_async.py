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

# 로깅 설정
logging.basicConfig(level=logging.INFO)

# === 기본 설정 ===
ROOM = "room1"            # 접속할 방 이름 (노드 서버에서 최대 2명 제한)
NICKNAME = "PythonClient" # 클라이언트 별칭 (필요에 따라 서버에 별도 전달 가능)

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
    가능한 경우 MediaPlayer를 이용하여 카메라/마이크 스트림을 추가한다.
    """
    global pc, player
    # STUN 서버를 이용한 기본 RTCConfiguration
    configuration = RTCConfiguration(
        iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
    )
    pc = RTCPeerConnection(configuration=configuration)
    logging.info("RTCPeerConnection 생성됨.")

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
            # 서버에 ICE candidate와 함께 방 이름을 함께 전송 (서버는 두 번째 인자는 room 식별용)
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
        logging.info("트랙 수신됨: %s", track.kind)
        # 예시로, track를 소비하기 위해 MediaBlackhole(데이터 폐기기)를 사용할 수 있음.
        recorder = MediaBlackhole()
        recorder.addTrack(track)
        asyncio.ensure_future(recorder.start())
        track.on("ended", lambda: asyncio.ensure_future(recorder.stop()))

    # --- 미디어 스트림 추가 (카메라/마이크) ---
    try:
        # Linux의 경우 기본 카메라 장치: /dev/video0, v4l2 형식
        player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "640x480"})
        logging.info("MediaPlayer를 통해 카메라 스트림을 가져옵니다.")
    except Exception as e:
        logging.warning("비디오 장치를 열 수 없습니다. 스트림 전송 없이 데이터 채널만 동작합니다. (%s)", e)
        player = None

    if player:
        # player.audio, player.video는 각각 트랙 리스트 (없으면 None)
        if player.audio:
            for track in player.audio:
                pc.addTrack(track)
        if player.video:
            for track in player.video:
                pc.addTrack(track)
    else:
        logging.info("미디어 스트림 추가 없음.")

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
