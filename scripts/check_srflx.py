import asyncio
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer

async def get_srflx_candidate(stun_url: str):
    configuration = RTCConfiguration(iceServers=[RTCIceServer(urls=stun_url)])
    pc = RTCPeerConnection(configuration=configuration)

    srflx_candidate = None

    @pc.on("icecandidate")
    def on_icecandidate(event):
        print("icecandidate event triggered")
        nonlocal srflx_candidate
        candidate = event.candidate
        if candidate and candidate.candidate and "typ srflx" in candidate.candidate:
            srflx_candidate = candidate
            print("srflx candidate found:", candidate.candidate)

    # 데이터 채널을 추가하여 offer 생성 조건을 만족시킴
    pc.createDataChannel("dummy")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    # ICE candidate 수집을 위한 대기 시간 (네트워크 상황에 따라 조정)
    await asyncio.sleep(30)
    await pc.close()
    return srflx_candidate

async def main():
    # 실제 coturn 서버의 주소와 포트로 교체하세요.
    stun_url = "stun:stun.l.google.com:19302"
    # stun_url = "stun:3.34.132.103:3478"
    candidate = await get_srflx_candidate(stun_url)
    if candidate:
        print("External (srflx) Address:", candidate.address)
        print("External (srflx) Port:", candidate.port)
    else:
        print("No srflx candidate found.")

if __name__ == "__main__":
    asyncio.run(main())
