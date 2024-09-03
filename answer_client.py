# ===============================================
# Title:  WebRTC Video Recorder Peer
# Author: gulbasozan
# Date:   26 Jul 2024
# ===============================================

import asyncio
import argparse
import logging
import uuid
import av

from aiortc import RTCPeerConnection, VideoStreamTrack, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.media import MediaRecorder, MediaRelay, MediaBlackhole
from aiortc.contrib.signaling import BYE, create_signaling, add_signaling_arguments

from aiohttp import web, ClientSession, WSMsgType
import json

logger = logging.getLogger("pc")
relay = MediaRelay()

# Normalize PTS to sync with the real-time webcam feed
class RemoteVideoStreamTrack(VideoStreamTrack):
    '''
        A video track with normalized PTS
    '''
    def __init__(self, track):
        super().__init__()
        self.track = track
    
    async def recv(self):
        print("RECV FUNCTION CALLED")
        frame = await self.track.recv()
        pts, time_base = await self.next_timestamp()
        # print(pts)
        frame.pts = pts
        frame.time_base = time_base
        # print("\n%s\n" % frame)
        logger.info("Frame recieved %s" % frame)

        try:
            logger.info("Converting to NDArray..")
            img = frame.to_ndarray(format="bgr24")
            # print(f"\nIMG:{img}\n")
            logger.info("Converted to NDArray: %s\n" % img)
        except av.error.ExitError as e:
            logger.info(f"Error converting frame to NDArray {e}")
            # print(f"Error converting frame to nd array {e}")
            return frame
        except Exception as e:
            logger.info(f"Unexpected error converting frame {e}")
            return frame

        logger.info("Retruning frame.\n")
        return frame

# Server Signaling
async def consumeSignaling(pc):
    print("WebSocket is starting..")
    session = ClientSession()
    async with session.ws_connect("http://0.0.0.0:8080/ws") as ws:
        status = False
        print("WebSocket connection established")
        opener = {"type": "opener", "sender": "answerClient"}
        await ws.send_json(opener)
        async for msg in ws:
            print(f"\n--------------------------------------\nMessage received: \n {msg.data}\n---------------------------------------------------")
            if msg.type == WSMsgType.TEXT:
                if msg.data == "close cmd":
                    await ws.close()
                    status = False
                    break
                else:
                    try:
                        data = json.loads(msg.data)
                        if data['type'] == "status" and data['status'] == "ready":
                            status = True
                        elif status and data['type'] == "offer":
                            print("Remote description is set")  
                            sdp = RTCSessionDescription(data['sdp'], data['type'])
                            if (pc.signalingState == "closed"): return
                            await pc.setRemoteDescription(sdp)

                            await pc.setLocalDescription(await pc.createAnswer())
                            message = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

                            await ws.send_json(message)
                    except Exception as e:
                        status = False
                        print(f"Hit to exception {e}")
            elif msg.type == WSMsgType.ERROR:
                break


# Copy-Paste Signaling
async def consume_signaling(pc, signaling):
    while True:
        obj = await signaling.receive()

        if isinstance(obj, RTCSessionDescription):
            await pc.setRemoteDescription(obj)

            if obj.type == "offer":
                #send answer
                await pc.setLocalDescription(await pc.createAnswer())
                await signaling.send(pc.localDescription)
            elif isinstance(obj, RTCIceCandidate):
                await pc.addIceCandidate(obj)
            elif obj is BYE:
                print("Exiting..")
                break

async def answer(
        pc, 
        # signaling, # Uncomment for copy-paste signaling
        recorder
        ):
    pc_id = "PeerConncetion(%s)" % uuid.uuid4()
    
    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    # Runs when the media transfer interface is initialized
    @pc.on("track")
    async def on_track(track):
        log_info("Track %s received", track.kind)
        print("Receiving %s", track.kind)

        # Init recoder to save the feed to a file
        recorder.addTrack(RemoteVideoStreamTrack(track))
        await recorder.start()

        # Runs when the interface is ended
        @track.on("ended")
        async def on_ended():
            log_info("Track %s ended", track.kind)

    # await signaling.connect() # Uncomment for copy-paste signaling

    # await consume_signaling(pc, signaling) # Uncomment for copy-paste signlaing
    await consumeSignaling(pc) # Commentout for copy-paste signaling

def rtc_eventloop():
    # signaling = create_signaling(args)
    pc = RTCPeerConnection()
    recorder = MediaBlackhole()
    # recorder = MediaRecorder("video.mp4")
    coro = answer(
        pc,
        # signaling, # Uncomment for copy-paste signaling 
        recorder
    )
    
    # Init event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Run event loop
    try:
        loop.run_until_complete(coro)
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(pc.close())
        # loop.run_until_complete(signaling.close()) # Uncomment for copy-paste signaling
        loop.run_until_complete(recorder.stop())
        loop.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Webcam stream")
    parser.add_argument("--verbose", "-v", action="count")
    add_signaling_arguments(parser)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    rtc_eventloop()


