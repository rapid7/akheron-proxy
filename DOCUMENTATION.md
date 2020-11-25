# Documentation for uart-proxy

## Introduction

The `uart-proxy` tool is designed to help lend visibility to UART inter-chip communications and aid in understanding/reversing those comms and device functionality.  It does this by supporting several modes of operation:

* forwarding/bridging traffic
  * passes/proxies traffic through from one device to the other (and vice-versa) while providing visibility of that data to the user
* capturing traffic
  * saves UART communication data to a file for examination and/or replay
* replaying traffic
  * loads captured data from a file and replays it on the UART connection
* replaying traffic with pattern replacement
  * loads captured data from a file, replacing user-provided pattern matches with user-provided replacement values, and replays it on the UART connection
  * also supports checksum recalculation+update on messages that have been altered

`TODO`: add note about physically accessing the comms on a device and wiring them to your system serial ports

## Use

Version 0.1 of the `uart-proxy` tool is first iteration on this effort, born of proof-of-concept code (blame @pbarry-r7 for the awful code in there).  It is a command-line tool, using a standard REPL for interaction.

### Requirements

The `uart-proxy` tool was tested under both macOS and Ubuntu 18.04, requiring Python 3.6 or later.  It uses `pyserial` for interfacing with system serial ports, you can read [here](https://pyserial.readthedocs.io/en/latest/pyserial.html) on how to install it on your system.

### Starting the tool

You can start the `uart-proxy` from a terminal window in the top-level directory of the repo:

`./uart_proxy.py`

NOTE: you may need `root` level permissions to access your serial port devices, in which case `sudo ./uart-proxy.py` will take care of that.

Once running, you'll see a banner and a `> ` prompt:

```
$ sudo ./uart-proxy.py 

##########################
Welcome to the UART Proxy!
          v0.1
##########################
	
> 
```

A number of commands are available at this prompt, which you can access by typing `help`:

```
> help

Documented commands (type help <topic>):
========================================
capturedump   delimget  list     replaceget  start
capturestart  delimset  portget  replaceset  stop 
capturestop   help      portset  replay      watch

Undocumented commands:
======================
exit  quit  version
```

You can get more help about a specific command by typing `help <command>`.

## Examples

### List available serial ports

```
> list
/dev/ttyS0
/dev/ttyUSB0
/dev/ttyUSB1
/dev/ttyUSB2
/dev/ttyUSB3
```

You can also get a verbose listing:
```
> list -v
/dev/ttyS0
    desc: ttyS0
    hwid: PNP0501
/dev/ttyUSB0
    desc: Quad RS232-HS
    hwid: USB VID:PID=0403:6011 LOCATION=1-1:1.0
/dev/ttyUSB1
    desc: Quad RS232-HS
    hwid: USB VID:PID=0403:6011 LOCATION=1-1:1.1
/dev/ttyUSB2
    desc: Quad RS232-HS
    hwid: USB VID:PID=0403:6011 LOCATION=1-1:1.2
/dev/ttyUSB3
    desc: Quad RS232-HS
    hwid: USB VID:PID=0403:6011 LOCATION=1-1:1.3
```

### Forward traffic and watch

The following steps will forward traffic between ports, 'watch' it, then stop traffic forwarding:

```
> portset A /dev/ttyUSB1 115200
> portset B /dev/ttyUSB2 115200
> start
Data now PASSING between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2"...
> watch
Watching data passed between ports. Press CTRL-C to stop...
A -> B: 0x61 0x61 0x73 0x73 0x64 0x64 
B -> A: 0x31 0x32 0x33 ^C
Watch mode exited.
> stop
Data now BLOCKED between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2".
> 
```

### Forward and capture (and watch) traffic

The following steps will forward traffic between ports, capture it to a file, watch it, then stop and dump capture contents, and then stop traffic forwarding:

```
> portset A /dev/ttyUSB1 115200
> portset B /dev/ttyUSB2 115200
> start
Data now PASSING between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2"...
> capturestart mycap.out
Saving captured traffic to "mycap.out"...
> watch
Watching data passed between ports. Press CTRL-C to stop...
A -> B: 0x31 0x32 0x33 
B -> A: 0x33 0x32 0x31 
A -> B: 0x20 0x20 0x20 
B -> A: 0x36 0x36 0x37 0x38 0x39 ^C
Watch mode exited.
> capturestop
Capture stopped
> capturedump mycap.out
    1: A -> B: 0x31 0x32 0x33
    2: B -> A: 0x33 0x32 0x31
    3: A -> B: 0x20 0x20 0x20
    4: B -> A: 0x36 0x36 0x37 0x38 0x39
> stop
Data now BLOCKED between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2".
> 
```

### Forward and replay traffic, then replay-with-pattern-replace, then replay-with-pattern-replace-and-recalculate-checksum

The following steps show forwarding traffic between ports with replay of data (a one-line capture dump file) in this sequence:

1. replay captured data exactly as it was originally captured (i.e. no modification)
1. set a replace operation to swap `0x64 0x61` sequences with `0x99 0x91` and replay (note the substituted data in the output)
1. set a checksum method to update the final byte of the message with a `Checksum8Modulo256Plus1` of the preceeding bytes and replay


```
> portset A /dev/ttyUSB1 115200
> portset B /dev/ttyUSB2 115200
> start
Data now PASSING between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2"...
> replay /tmp/aaa
Replaying data from A -> B, press CTRL-C to exit watch mode...
A -> B: 0x61 0x73 0x64 0x61 0x73 0x64 ^C
Watch mode exited.
> replaceset A 0x64 0x61 -> 0x99 0x91
> replaceget
Replace port A pattern X -> pattern Y:
  0x64 0x61 -> 0x99 0x91
Replace port B pattern X -> pattern Y:
> replay /tmp/aaa
Replaying data from A -> B, press CTRL-C to exit watch mode...
A -> B: 0x61 0x73 0x99 0x91 0x73 0x64 ^C
Watch mode exited.
> checksumset A 3
> checksumget
Replace on port A using checksum 'Checksum8Modulo256Plus1'
No replace checksum specified on port B
> replay /tmp/aaa
Replaying data from A -> B, press CTRL-C to exit watch mode...
A -> B: 0x61 0x73 0x99 0x91 0x73 0x72 ^C
Watch mode exited.
> stop
Data now BLOCKED between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2".
>
```

