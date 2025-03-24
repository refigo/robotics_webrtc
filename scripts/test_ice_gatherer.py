import asyncio
from aiortc import RTCIceGatherer, RTCIceServer

async def gather_ice_candidates():
    # RTCIceServer를 사용해 STUN 서버를 설정합니다.
    # 여기서는 Google의 공개 STUN 서버를 예시로 사용합니다.
    ice_server = RTCIceServer(urls=["stun:3.34.132.103:3478"])
    # ice_server = RTCIceServer(urls=["stun:stun.l.google.com:19302"])
    
    # RTCIceGatherer를 생성할 때 iceServers 파라미터로 STUN 서버 리스트를 전달합니다.
    gatherer = RTCIceGatherer(iceServers=[ice_server])
    
    # ICE 후보를 수집합니다.
    await gatherer.gather()
    
    # 수집된 ICE 후보들을 가져옵니다.
    local_candidates = gatherer.getLocalCandidates()
    local_parameters = gatherer.getLocalParameters()
    return local_candidates, local_parameters

async def main():
    candidates, parameters = await gather_ice_candidates()
    print("Local ICE Parameters:")
    print(parameters)
    print("\nGathered ICE Candidates:")
    for candidate in candidates:
        print(candidate)

if __name__ == "__main__":
    asyncio.run(main())
