import asyncio
import socketio

sio = socketio.AsyncClient()

@sio.event
async def connect():
    print('connection established')

@sio.event
async def my_message(data):
    print('message received with ', data)
    await sio.emit('my response', {'response': 'my response'})

@sio.event
async def disconnect():
    print('disconnected from server')


@sio.event
async def welcome(user, newCount):
    print(f"{user} arrived! - ({newCount})")

@sio.event
async def bye(left, newCount):
    print(f"{left} left ㅠㅠ - ({newCount})")

@sio.event
async def new_message(msg):
    print(msg)


async def showRoom():
    print("Check-in Room")



async def main():
    await sio.connect('http://localhost:3000')
    print("wait..")
    await sio.wait()

if __name__ == '__main__':
    asyncio.run(main())