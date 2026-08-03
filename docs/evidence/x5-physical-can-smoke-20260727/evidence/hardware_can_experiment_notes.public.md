# Hardware CAN Experiment Notes

- TX interface: can1
- RX interface: can2
- Bitrate: 500000
- Duration: 40s
- ACK delay: 5 ms
- ACK timeout: 80 ms
- Camera source: v4l2
- Camera device: /dev/video0
- Camera frames: <CAPTURE_ROOT>/camera_frames
- RuntimeEvent log: <CAPTURE_ROOT>/runtime_events.jsonl
- TX candump: <CAPTURE_ROOT>/candump_can1.log
- RX candump: <CAPTURE_ROOT>/candump_can2.log
- ACK responder log: <CAPTURE_ROOT>/ack_responder.jsonl
