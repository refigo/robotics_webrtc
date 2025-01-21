import http from "http";
import SocketIO from "socket.io"
import express from "express";

const app = express();

app.set("view engine", "pug");
app.set("views", __dirname + "/views");
app.use("/public", express.static(__dirname + "/public"));
app.get("/", (_, res) => res.render("home"));
app.get("/*", (_, res) => res.redirect("/"));

const handleListen = () => console.log(`Listening on: http://localhost:3000`);

const httpServer = http.createServer(app);
const wsServer = SocketIO(httpServer);

function publicRooms() {
    const {
        sockets: {
            adapter: {sids, rooms},
        },
    } = wsServer;
    // or
    // const sids = wsServer.sockets.adpater.sids;
    // const rooms = wsServer.sockets.adapter.rooms;
    
    const publicRooms = [];
    rooms.forEach((_, key) => {
        if (sids.get(key) === undefined) {
            publicRooms.push(key);
        }
    })
    return publicRooms;
}

wsServer.on("connection", (socket) => {
    socket["nickname"] = "Anon";
    console.log("connection!")
    socket.onAny((event) => {
        console.log(wsServer.sockets.adapter);
        console.log(`Socket Event: ${event}`);
    });
    socket.on("enter_room", (roomName, done) => {
        socket.join(roomName);
        console.log(`roomName: ${roomName}`)
        done();
        socket.to(roomName).emit("welcome", socket.nickname);
    });
    socket.on("disconnecting", () => {
        socket.rooms.forEach((room) => socket.to(room).emit("bye", socket.nickname));
        console.log("disconnecting..")
    });
    socket.on("new_message", (msg, room, done) => {
        socket.to(room).emit("new_message", `${socket.nickname}: ${msg}`);
        done();
    });
    socket.on("nickname", (nickname) => (socket["nickname"] = nickname));
});

/*
function onSocketClose() {
    console.log("Disconnected from the Browser ❌")
}

const sockets = [];

wss.on("connection", (socket) => {
    sockets.push(socket);
    socket["nickname"] = "Anonymous"
    console.log("Connected to Browser ✅");
    socket.on("close", onSocketClose);
    socket.on("message", (msg) => {
        const message = JSON.parse(msg);
        switch (message.type) {
            case "new_message":
                // console.log("new_message: ", )
                sockets.forEach((aSocket) => 
                    aSocket.send(`${socket.nickname}: ${message.payload}`)
                );
                console.log(`${socket.nickname}: ${message.payload}`)
                break;
            case "nickname":
                socket["nickname"] = message.payload;
                console.log("socket.nickname: ", socket.nickname);
        }
    });
});
*/

httpServer.listen(3000, handleListen);


