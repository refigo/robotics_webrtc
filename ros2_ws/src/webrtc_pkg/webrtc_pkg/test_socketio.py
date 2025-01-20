import socketio

sio = socketio.Client();

@sio.event
def connect():
    print("Connected to server")

@sio.event
def disconnect():
    print("Disconnected from server")

@sio.event
def connect_error(data):
    print("Connection failed:", data)

def showRoom():
    print("Check-in Room")

def main():
    try:
        sio.connect('http://localhost:3000')

        roomName = "exampleRoom"
        sio.emit("enter_room", {"roomName": roomName}, callback=showRoom)

        sio.wait()

    except Exception as e:
        print("An error occurred:", e)

if __name__ == "__main__":
    main()
