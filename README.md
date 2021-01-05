# Akheron Proxy

## Introduction

The `akheron` tool is written in python and designed to help lend visibility to UART inter-chip communications and aid in understanding, reversing, and manipulating those communications to discern device functionality (both intended and unintended).  It does this by supporting several modes of operation:

* Bridging communications - proxies data between devices while providing visibility to the data
* Capturing communications - saves UART communication data to a file for examination and replay
* Replaying communications - loads captured data from a file and replays it on the UART connection
  * Supports replay with user-provided pattern match and replacement values
  * Supports replay with checksum recalculation and message updates

## Physical setup

Inter-chip communication via UART is still a common design choice found in many devices, and it looks something like this:

```
+------------+                           +------------+
|        TXD +-------------------------->+ RXD        |
| CHIP A     |                           |     CHIP B |
|        RXD +<--------------------------+ TXD        |
+------------+                           +------------+

```

In this example, chip A sends data to chip B by sending data out chip A's transmit (TX) pin and chip B receives that incoming data on its receive (RX) pin. Chip B sends data out its transmit (TX) pin to be received by chip A on chip A's receive (RX) pin.

But what exactly are they sending back and forth between each other?

If we make ourselves a physical machine-in-the-middle, we can find out!

The `akheron` tool is designed to be run on a system with two serial ports (USB-to-serial adapters are fine, so long as the OS of the system supports them), acting as a proxy for sending traffic between those two ports.  Something like this:

```
    ^     +             ^     +
    |     v             |     v
+---------------------------------+
| |TXD1 RXD1|         |TXD2 RXD2| |
| +---------+         +---------+ |
|   UART  1             UART  2   |
|                                 |
|     Machine-in-the-Middle       |
|    (running Akheron Proxy)      |
|                                 |
+---------------------------------+
```

If we physically cut the communication traces between chip A and chip B and then route them to our machine-in-the-middle's serial ports, we'll be able to see what those chips are sending each other over their UART communications with `akheron`:

```
+------------+                               +------------+
|        TXD +--------+             +------->+ RXD        |
| CHIP A     |        |             |        |     CHIP B |
|        RXD +<-+     |             |     +--+ TXD        |
+------------+  |     |             |     |  +------------+
                |     |             |     |
                |     v             |     v
            +---------------------------------+
            | |TXD1 RXD1|         |TXD2 RXD2| |
            | +---------+         +---------+ |
            |   UART  1             UART  2   |
            |                                 |
            |     Machine-in-the-Middle       |
            |    (running Akheron Proxy)      |
            |                                 |
            +---------------------------------+
```

With a setup as such, `akheron` is ready for use!

## Command-Line Tool

`akheron` version 0.1 is the first iteration on this effort and born of proof-of-concept code. It is a command-line tool, using a standard REPL for interaction.

### Requirements

The `akheron` tool requires Python 3.6 or later, and uses the [`pyserial`](https://pyserial.readthedocs.io/en/latest/pyserial.html) library for interfacing with the system's serial ports. It was tested on both macOS 10.15 and Ubuntu 18.04.

#### Install Requirements
```
pip install -r requirements.txt
```

### Starting the tool

You can start `akheron` from a terminal window in the top-level directory of the repo:

`./akheron.py`

On many systems, access to serial devices is restricted. To avoid running `akheron` with elevated privileges, ensure that your user account belongs to the same group as the device you wish to use. On Linux, the serial device is likely a member of the `dialout` group. Adding your user account to that group (e.g. `sudo usermod -a -G dialout $USER`) should allow you to access the device. In order for you to see the changes, you may need to logout and log back in to your account, or possibly reboot the system.

Once running, you'll see a banner and a `> ` prompt:

```
$ ./akheron.py

######################################################
Akheron Proxy, UART proxy tool for inter-chip analysis
                     version 0.1
######################################################

> 
```

A number of commands are available at this prompt, which you can access by typing `help`:

```
> help

Documented commands (type help <topic>):
========================================
capturedump   checksumget  delimset  portget     replaceset  stop
capturestart  checksumset  help      portset     replay      watch
capturestop   delimget     list      replaceget  start

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

#### With start-of-message delimiter

This is the same flow, but with a start-of-message delimiter of `0x37` set:

```
> portset A /dev/ttyUSB1 115200
> portset B /dev/ttyUSB2 115200
> delimset start 0x37
> start
Data now PASSING between ports "/dev/ttyUSB1" <-> "/dev/ttyUSB2"...
> watch
Watching data passed between ports. Press CTRL-C to stop...
A -> B: 0x37 0x71 0x77 0x65 0x65 0x72 
        0x37 0x64 0x66 0x61 0x64 
        0x37 0x73 
        0x37 0x68 0x68 
B -> A: 0x37 0x6e 0x6d 0x62 
        0x37 0x69 0x69 
A -> B: 0x37 0x61 0x73 0x64 ^C
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

The following steps show forwarding traffic between ports with replay of data (in this example, a capture file that contains a single line) in this sequence:

1. replay captured data exactly as it was originally captured (i.e. no modification)
1. set a replace operation to swap `0x64 0x61` sequences with `0x99 0x91` and replay (note the substituted data in the output)
1. set a checksum method to update the final byte of the message with a `Checksum8Modulo256Plus1` of the preceding bytes and replay


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
