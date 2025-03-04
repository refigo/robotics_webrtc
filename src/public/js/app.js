const socket = io();

// DOM
const welcome = document.getElementById("welcome");
const welcomeForm = welcome.querySelector("form");
const room = document.getElementById('room');
const nameForm = room.querySelector('#name');
const nicknameDisplay = nameForm.querySelector('h4');

room.hidden = true;

let nickname = 'Anonymous';
// let roomName;

// Video
const myFace = document.getElementById("myFace");
const muteBtn = document.getElementById("mute");
const cameraBtn = document.getElementById("camera");
const camerasSelect = document.getElementById("cameras");
const call = document.getElementById("call");

// call.hidden = true

let myStream;
let muted = true;
let cameraOff = true;
let roomName;
let myPeerConnection;
let myDataChannel;

async function getCameras() {
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const cameras = devices.filter(device => device.kind === "videoinput");
        const currentCamera = myStream.getVideoTracks()[0];
        // console.log(currentCamera);
        cameras.forEach((camera) => {
            const option = document.createElement("option");
            option.value = camera.deviceId;
            option.innerText = camera.label;
            if (currentCamera.label === camera.label) {
                option.selected = true;
            }
            camerasSelect.appendChild(option);
        });
    } catch (e) {
        console.log(e);
    }
}

async function getMedia(deviceId) {
    const initialConstraints = {
        audio: true,
        video: { facingMode: "user" },
    };
    const cameraConstraints = {
        audio: true,
        video: {
            deviceId: {
                exact: deviceId,
            }
        }
    };
    try {
        myStream = await navigator.mediaDevices.getUserMedia(
            deviceId ? cameraConstraints : initialConstraints
        );
    } catch (e) {
        console.log("Local media access failed:", e);
        // Create empty stream for local media
        myStream = new MediaStream();
        // Still proceed with the call setup
        if (!deviceId) {
            await getCameras();
        }
    }
    
    if (muted) {
        myStream.getAudioTracks().forEach(track => track.enabled = false);
    }
    if (cameraOff) {
        myStream.getVideoTracks().forEach(track => track.enabled = false);
    }
    
    myFace.srcObject = myStream; 
}

function handleMuteClick() {
    myStream
        .getAudioTracks()
        .forEach((track) => (track.enabled = !track.enabled));
    if (!muted) {
        muteBtn.innerText = "Unmute";
        muted = true;
    } else {
        muteBtn.innerText = "Mute";
        muted = false;
    }
}

function handleCameraClick() {
    myStream
        .getVideoTracks()
        .forEach((track) => (track.enabled = !track.enabled));
    if (cameraOff) {
        cameraBtn.innerText = "Turn Camera Off";
        cameraOff = false;
    } else {
        cameraBtn.innerText = "Turn Camera On";
        cameraOff = true;
    }
}

async function handleCameraChange() {
    await getMedia(camerasSelect.value);
    if (myPeerConnection) {
        const videoTrack = myStream.getVideoTracks()[0];
        const videoSender = myPeerConnection
            .getSenders()
            .find((sender) => sender.track.kind === "video");
        videoSender.replaceTrack(videoTrack);
    }
}

muteBtn.addEventListener("click", handleMuteClick);
cameraBtn.addEventListener("click", handleCameraClick);
camerasSelect.addEventListener("input", handleCameraChange);


// Welcome Form (join a room)

async function initCall() {
    // welcome.hidden = true;
    // call.hidden = false;
    await getMedia();
    makeConnection();
}

function showLobby() {
    welcome.hidden = false;
    room.hidden = true;
    roomName = null;
}

function addMessage(message) {
    const ul = room.querySelector('ul');
    const li = document.createElement('li');
    li.innerText = message;
    ul.appendChild(li);
}

function handleMessageSubmit(event) {
    event.preventDefault();
    const input = room.querySelector('#msg input');
    const value = input.value;
    socket.emit('new_message', input.value, roomName, () => {
        addMessage(`You(${nickname}): ${value}`);
    });
    input.value = '';
}

function handleNicknameSubmit(event) {
    event.preventDefault();
    const input = room.querySelector('#name input');
    socket.emit('nickname', input.value);
    nickname = input.value;
    nicknameDisplay.innerText = `Current your nickname: ${nickname}`;
    input.value = '';
}

function handleLeaveRoom(event) {
    console.log(`leave room!`);
    cleanupWebRTC();
    socket.emit('leave_room', roomName, showLobby);
}

function showRoom() {
    welcome.hidden = true;
    room.hidden = false;
    const h2 = room.querySelector('h2');
    h2.innerText = `Room ${roomName}`;
    const msgForm = room.querySelector('#msg');
    nicknameDisplay.innerText = `Current your nickname: ${nickname}`;
    msgForm.addEventListener('submit', handleMessageSubmit);
    nameForm.addEventListener('submit', handleNicknameSubmit);
    const leaveBtn = room.querySelector('#leave');
    leaveBtn.addEventListener('click', handleLeaveRoom);
  }

async function handleWelcomeSubmit(event) {
    event.preventDefault();
    const input = welcomeForm.querySelector("input");
    await initCall();
    socket.emit("join_room", input.value, showRoom);
    roomName = input.value;
    input.value = "";
}

welcomeForm.addEventListener("submit", handleWelcomeSubmit);


// Socket Code

socket.on("welcome", async (user) => {
    myDataChannel = myPeerConnection.createDataChannel("chat");
    myDataChannel.addEventListener("message", (event) => {
        console.log(event.data);
    });
    console.log("made data channel")

    const offer = await myPeerConnection.createOffer();
    myPeerConnection.setLocalDescription(offer);
    socket.emit("offer", offer, roomName);
    console.log("sent the offer");
    addMessage(`${user} arrived!`);
});

socket.on("offer", async (offer) => {
    myPeerConnection.addEventListener("datachannel", (event) => {
        myDataChannel = event.channel;
        myDataChannel.addEventListener("message", (event) => {
            console.log(event.data);
        });
    });

    console.log("received the offer")
    myPeerConnection.setRemoteDescription(offer);
    const answer = await myPeerConnection.createAnswer();
    myPeerConnection.setLocalDescription(answer);
    socket.emit("answer", answer, roomName);
    console.log("sent the answer")
});

socket.on("answer", (answer) => {
    console.log("received the answer")
    myPeerConnection.setRemoteDescription(answer);
});

socket.on("ice", (ice) => {
    if (!myPeerConnection) {
        console.warn("[ICE] No peer connection to add candidate");
        return;
    }
    
    if (ice) {
        const candidateStr = ice.candidate;
        console.log("[ICE] Raw received candidate:", candidateStr);
        
        // Parse candidate components
        const parts = candidateStr.split(' ');
        if (parts.length >= 8) {  // Ensure we have minimum required parts
            const candidateInfo = {
                foundation: parts[0].split(':')[1],
                component: parts[1],
                protocol: parts[2],
                priority: parts[3],
                ip: parts[4],
                port: parts[5],
                type: parts[7]
            };
            
            // Add raddr/rport if present (for srflx candidates)
            if (parts.length > 9 && parts[8] === "raddr") {
                candidateInfo.relatedAddress = parts[9];
                candidateInfo.relatedPort = parts[11];
            }
            
            console.log("[ICE] Parsed candidate:", candidateInfo);
            
            // Create proper RTCIceCandidate object
            const candidate = new RTCIceCandidate({
                candidate: candidateStr,
                sdpMid: ice.sdpMid,
                sdpMLineIndex: ice.sdpMLineIndex
            });
            
            myPeerConnection.addIceCandidate(candidate)
                .catch(err => console.error("[ICE] Error adding candidate:", err));
        } else {
            console.warn("[ICE] Invalid candidate format:", candidateStr);
        }
    } else {
        console.log("[ICE] Remote gathering complete - null candidate");
    }
});

socket.on('bye', (left) => {
    // cleanupWebRTC();
    addMessage(`${left} left the room. ㅠㅠ`);
});

socket.on('new_message', addMessage);

socket.on("room_change", (rooms) => {
    const roomList = welcome.querySelector("ul");
    roomList.innerHTML = "";
    if (rooms.length === 0) {
        return;
    }
    rooms.forEach((room) => {
        const li = document.createElement("li");
        li.innerText = `${room.roomName} (${room.userCount}/2)`;
        roomList.append(li);
    });
});

socket.on("room_full", () => {
    alert("This room is full. Maximum 2 users allowed.");
    window.location.reload();
});

// RTC Code

function makeConnection() {
    myPeerConnection = new RTCPeerConnection({
        iceServers: [
            {
                urls: [
                    "stun:3.34.132.103:3478",
                    // "stun:stun.l.google.com:19302",
                    // "stun:stun1.l.google.com:19302",
                    // "stun:stun2.l.google.com:19302",
                    // "stun:stun3.l.google.com:19302",
                    // "stun:stun4.l.google.com:19302",
                ],
            },
        ],
    });
    console.log("[RTC] Created peer connection with config:", myPeerConnection.getConfiguration());

    // Log all state changes
    myPeerConnection.oniceconnectionstatechange = () => {
        console.log("[ICE] Connection state changed:", myPeerConnection.iceConnectionState);
    };
    myPeerConnection.onicegatheringstatechange = () => {
        console.log("[ICE] Gathering state changed:", myPeerConnection.iceGatheringState);
    };
    myPeerConnection.onconnectionstatechange = () => {
        console.log("[RTC] Connection state changed:", myPeerConnection.connectionState);
    };
    myPeerConnection.onsignalingstatechange = () => {
        console.log("[RTC] Signaling state changed:", myPeerConnection.signalingState);
    };

    myPeerConnection.addEventListener("icecandidate", handleIce);
    myPeerConnection.addEventListener("addstream", handleAddStream);
    
    // Only add tracks if we have a stream with tracks
    if (myStream && myStream.getTracks().length > 0) {
        myStream.getTracks().forEach((track) => myPeerConnection.addTrack(track, myStream));
    }
}

function handleIce(data) {
    if (data.candidate) {
        const candidateStr = data.candidate.candidate;
        console.log("[ICE] Raw generated candidate:", candidateStr);
        
        // Parse candidate components
        const parts = candidateStr.split(' ');
        if (parts.length >= 8) {  // Ensure we have minimum required parts
            const candidateInfo = {
                foundation: parts[0].split(':')[1],
                component: parts[1],
                protocol: parts[2],
                priority: parts[3],
                ip: parts[4],
                port: parts[5],
                type: parts[7]
            };
            
            // Add raddr/rport if present (for srflx candidates)
            if (parts.length > 9 && parts[8] === "raddr") {
                candidateInfo.relatedAddress = parts[9];
                candidateInfo.relatedPort = parts[11];
            }
            
            console.log("[ICE] Parsed candidate:", candidateInfo);
            
            // Create proper RTCIceCandidate object
            const candidate = new RTCIceCandidate({
                candidate: candidateStr,
                sdpMid: data.candidate.sdpMid,
                sdpMLineIndex: data.candidate.sdpMLineIndex
            });
            
            socket.emit("ice", candidate, roomName);
        } else {
            console.warn("[ICE] Invalid candidate format:", candidateStr);
        }
    } else {
        console.log("[ICE] Gathering complete - null candidate");
    }
}

function handleAddStream(data) {
    console.log("Received remote stream", data.stream);
    
    const peerFace = document.getElementById("peerFace");
    if (!peerFace) {
        console.error("peerFace element not found!");
        return;
    }
    
    // Log stream details
    console.log("Remote stream details:", {
        active: data.stream.active,
        id: data.stream.id,
        trackCount: data.stream.getTracks().length
    });
    
    peerFace.srcObject = data.stream;
    
    // Add event listeners to track stream status
    data.stream.getTracks().forEach(track => {
        console.log(`Remote track added:`, {
            kind: track.kind,
            enabled: track.enabled,
            id: track.id,
            readyState: track.readyState,
            muted: track.muted
        });
        
        track.onended = () => console.log(`Remote track ended: ${track.kind}`);
        track.onmute = () => console.log(`Remote track muted: ${track.kind}`);
        track.onunmute = () => console.log(`Remote track unmuted: ${track.kind}`);
    });
    
    // Add video element event listeners
    peerFace.onloadedmetadata = () => {
        console.log("Video metadata loaded", {
            videoWidth: peerFace.videoWidth,
            videoHeight: peerFace.videoHeight
        });
        // Attempt to play the video
        peerFace.play().catch(e => console.error("Error playing video:", e));
    };
    peerFace.onplay = () => console.log("Video started playing");
    peerFace.onpause = () => console.log("Video paused");
    peerFace.onerror = (e) => console.error("Video error:", e);
}

function cleanupWebRTC() {
    if (myPeerConnection) {
        // Close data channel if it exists
        if (myDataChannel) {
            myDataChannel.close();
            myDataChannel = null;
        }

        // Close all tracks
        if (myStream) {
            myStream.getTracks().forEach(track => {
                track.stop();
            });
        }

        // Close peer connection
        myPeerConnection.close();
        myPeerConnection = null;
    }

    // Clear video elements
    if (myFace) myFace.srcObject = null;
    const peerFace = document.getElementById("peerFace");
    if (peerFace) peerFace.srcObject = null;
}
