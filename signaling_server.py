# ===============================================
# Title:  Simple Signaling Server
# Author: gulbasozan
# Date:   26 Jul 2024
# ===============================================

from aiohttp import web, WSMsgType

import json
import time
from datetime import datetime

routes = web.RouteTableDef()
clients = {}

def logger(msg):
    print(f"[{datetime.fromtimestamp(time.time())}] {msg}")

@routes.get('/')
async def hello(reuest):
    return web.Response(text="Hello World")

@routes.get('/answer')
async def webSocketHandler(reuest):
    ws = web.WebSocketResponse()
    await ws.prepare(reuest)


@routes.get('/ws')
async def webSocketHandler(reuest):
    ws = web.WebSocketResponse()
    await ws.prepare(reuest)

    client_id = None
    
    async for msg in ws:
        # logger(f"Message recevied: {msg}")
        if msg.type == WSMsgType.TEXT:
            if msg.data == 'close':
                await ws.close()
            else:
                try:
                    data = json.loads(msg.data)
                    if 'type' in data:
                        match data['type']:
                            # Make sure two peers connected before signaling
                            case "opener":
                                client_id = data['sender']
                                clients[client_id] = ws
                                logger(f"Client {client_id} connected")

                                if 'browser' in clients and 'robotino' in clients:
                                    await clients['browser'].send_str(json.dumps({"type":"status","status": "ready"}))
                                    await clients['robotino'].send_str(json.dumps({"type": "status", "status": "ready"}))

                                elif 'browser' in clients:
                                    await clients['browser'].send_str(json.dumps({"type": "status", "status": "waiting for robotino"}))

                                elif 'robotino' in clients and 'answerClient' not in clients:
                                    await clients['robotino'].send_str(json.dumps({"type": "status", "status": "waiting for browser"}))

                                if 'answerClient' in clients and 'robotino' in clients:
                                    await clients['robotino'].send_str(json.dumps({"type":"status","status": "ready"}))
                                    await clients['answerClient'].send_str(json.dumps({"type": "status", "status": "ready"}))

                                elif 'answerClient' in clients:
                                    await clients['answerClient'].send_str(json.dumps({"type": "status", "status": "waiting for robotino"}))

                                elif 'robotino' in clients and 'browser' not in clients:
                                    await clients['robotino'].send_str(json.dumps({"type": "status", "status": "waiting for answerClient"}))

                                else: break 
                            
                            case "offer":
                                for cid, ws in clients.items():
                                    if cid != client_id:
                                        logger(f"Signaling Offer to {cid}")
                                        await ws.send_str(json.dumps(data))
 
                            case "answer":
                                for cid, ws in clients.items():
                                    if cid != client_id:
                                        logger(f"Signaling Answer to {cid}")
                                        await ws.send_str(json.dumps(data))

                            case _:
                                break
                    else: logger("Undefined message recevied!")
                except Exception as e:
                    logger("Couldnot convert/or send data %s" % e)
        elif msg.type == WSMsgType.ERROR:
            logger("WS connection closed with exception %s" % ws.exception())
    
    logger(f"Client {client_id} is disconnected.")

    if client_id in clients:
        del clients[client_id]

    return ws


app = web.Application()
app.add_routes(routes)

web.run_app(app)