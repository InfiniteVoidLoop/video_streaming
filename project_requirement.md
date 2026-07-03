# Socket Programming Project Video Streaming using IP Multicast

**Description**\
Implement a multicast video streaming application. The server
continuously broadcasts MJPEG video frames to a multicast group, and
multiple clients join the group to watch the stream. No RTSP, RTP,
TCP/UDP selection, or separate control/data channels are required.

## Architecture

Server -\> Multicast Group (239.1.1.1:5004) -\> Multiple Clients

![](media/image1.png){width="4.40625in" height="4.0625in"}

## Functional Requirements

Server:

-   Read a MJPEG video file frame by frame.

-   Packetize each frame.

-   Send every frame to a multicast IP address.

-   Broadcast frames at approximately 20 FPS (50 ms/frame).

-   Continue streaming until the video ends.

-   Restart the video automatically after reaching the last frame

    Client:

-   Join the multicast group.

-   Receive multicast packets.

-   Decode received packets.

-   Display the video in real time.

-   Leave the multicast group when exiting.

## Running

Server:\
python Server.py \<file MJPEG\>\
\
Client:\
python Client.py

## Grading Rubric (10 pts)

  ----------------------- ----------------------- ------------------------
  Requirement             Points                  Description

  Server implementation   2.5                     Multicast server

  Client implementation   2.5                     Receive/display video

  Packet format           2.0                     Custom packet

  Multiple clients & loss 2.0                     Concurrency/statistics
  detection                                       

  Report                  1.0                     Architecture/testing
  ----------------------- ----------------------- ------------------------
