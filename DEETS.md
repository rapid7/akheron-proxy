# Overview - DRAFT

## Design

### High-level design diagram

```
+---------------+      +-------------------------+
|               +----->+                         |
|   Serial      |      |   Command and Capture   |
|   Processor   |      |        Component        |
|               +<-----+                         |
+-+-+-----------+      +-+-+-----------------+-+-+
  | ^                    | ^                 ^ |
  | |                    | |                 | |
  | |                    | |                 | |
  | |                    | |                 | |
  v |                    v |                 | v
+-+-+--------+      +----+-+-------+ +-------+-+----+
|            |      |              | |              |
|   Serial   |      |     REPL     | |   Web App    |
|  Hardware  |      |              | |              |
|            |      |              | |              |
+------------+      +--------------+ +--------------+
```



## Features

Modes when interacting with the serial traffic:
* sniff/passthrough
* replay
* replace/substitute

# Roadmap - DRAFT

## Version 0.X - Prototyping/PoC

## Version 1.0 - Command Line

## Version 2.0 - Web UI
