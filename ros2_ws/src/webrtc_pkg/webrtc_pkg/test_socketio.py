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


@sio.event
def welcome(user, newCount):
    print(f"{user} arrived! - ({newCount})")

@sio.event
def bye(left, newCount):
    print(f"{left} left ㅠㅠ - ({newCount})")

@sio.event
def new_message(msg):
    print(msg)


def showRoom():
    print("Check-in Room")

def main():
    try:
        # sio.connect('http://localhost:3000')
        sio.connect('http://192.168.20.67:3000')

        roomName = "asdf"
        sio.emit("enter_room", roomName, callback=showRoom)

        print("wait..")
        sio.wait()

    except Exception as e:
        print("An error occurred:", e)

if __name__ == "__main__":
    main()
