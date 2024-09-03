# ===============================================
# Title:  WebRTC Webcam Stream Peer
# Author: gulbasozan
# Date:   26 Jul 2024
# ===============================================

import asyncio
import argparse
import logging
import uuid
import fractions
import time
from typing import Tuple

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate
from aiortc.contrib.signaling import BYE, create_signaling, add_signaling_arguments
from aiortc.contrib.media import MediaPlayer, MediaStreamTrack

from aiohttp import web, ClientSession, WSMsgType
import json

AUDIO_PTIME = 0.020 # 20ms audio packetization
VIDEO_CLOCK_RATE = 90000
VIDEO_PTIME = 1 / 30  # 30fps
# VIDEO_PTIME = 1 / 15  # 30fps       # this gets reset based on a ROS2 parameter
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)

class MediaStreamError(Exception):
    pass

logger = logging.getLogger("pc")


# Normalized VideoStreamTrack

class VideoStreamTrack(MediaStreamTrack):
    kind = "video"

    _start: float
    _timestamp: int

    def __init__(self, track):
        super().__init__()
        self.track = track

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        if self.readyState != "live":
            raise MediaStreamError

        if hasattr(self, "_timestamp"):
            self._timestamp += int(VIDEO_PTIME * VIDEO_CLOCK_RATE)
            wait = self._start + (self._timestamp / VIDEO_CLOCK_RATE) - time.time()
            await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0
        return self._timestamp, VIDEO_TIME_BASE    

    async def recv(self):
        frame = await self.track.recv()
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base
        return frame

async def consumeSignaling(pc):
    print("WebSocket is starting..")
    session = ClientSession()

    async with session.ws_connect("http://0.0.0.0:8080/ws") as ws:
        print("WebSocket connection established")
        opener = {"type": "opener", "sender": "robotino"}
        await ws.send_json(opener)

        async for msg in ws:
            print(f"\n--------------------------------------\nMessage received: \n {msg.data}\n---------------------------------------------------")
            if msg.type == WSMsgType.TEXT:
                if msg.data == "close cmd":
                    await ws.close()
                    break
                else:
                    try:
                        data = json.loads(msg.data)
                        if data['type'] == "status" and data['status'] == "ready":
                            if pc.signalingState == "closed": return # TODO: Instead of exiting, handle remote peer disconnection
                            message = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}

                            await ws.send_json(message)
                        elif data['type'] == "answer":
                            print("Remote description is set " )
                            sdp = RTCSessionDescription(data['sdp'], data['type'])

                            await pc.setRemoteDescription(sdp)
                    except Exception as e:
                        print(f"Hit to exception {e}")
            elif msg.type == WSMsgType.ERROR:
                break

# Copy-Paste Signaling
async def consume_signaling(pc, signaling):
    while True:
        obj = await signaling.receive()

        if isinstance(obj, RTCSessionDescription):
            await pc.setRemoteDescription(obj)

            if obj.type == "moffer":
                #send answer
                await pc.setLocalDescription(await pc.createAnswer())
                await signaling.send(pc.localDescription)
            elif isinstance(obj, RTCIceCandidate):
                await pc.addIceCandidate(obj)
            elif obj is BYE:
                print("Exiting..")
                break

async def offer(
        pc,
        #signaling # Uncomment for copy-paste signaling
        ):
    pc_id = "PeerConnection(%s)" % uuid.uuid4()

    def log_info(msg, *args):
        logger.info(pc_id + " " + msg, *args)

    # await signaling.connect() # Uncomment for copy-paste signaling

    # open media source
    options = {"framerate": "30", "video_size": "640x480"}
    player = MediaPlayer("/dev/video0", format="v4l2", options=options)
    log_info("Media source is created %s", player)

    @pc.on("track")
    def on_track(track):
        logger.debug("Track %s received", track.kind)

        if track.kind == "audio":
            pass
        elif track.kind == "video":
            #this should not get called - as we're only pushing one way
            logger.error("on_track - should not get video track")

            # add our locally generated video track here
            pc.addTrack(VideoStreamTrack(player.video))
            log_info("Track added %s to pc", player.video.kind)

    # Init media transfer interface
    pc.addTrack(VideoStreamTrack(player.video))

    # send offer
    await pc.setLocalDescription(await pc.createOffer())
    # await signaling.send(pc.localDescription) # Uncomment for copy-paste signaling

    # await consume_signaling(pc, signaling) # Uncomment for copy-paste signaling
    await consumeSignaling(pc) # Commentout for copy-paste signaling

def rtc_eventloop(args):
    # signaling = create_signaling(args) # Uncomment for copy-paste signlaing
    pc = RTCPeerConnection()
    coro = offer(
        pc, 
        # signaling # Uncomment for copy-paste signaling
        )   

    # Init the event loop
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
        loop.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Webcam stream")
    parser.add_argument("--verbose", "-v", action="count")
    add_signaling_arguments(parser)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    rtc_eventloop(args)