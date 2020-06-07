# Test tools

## port-runner
Simple C program for transmitting traffic out one serial port and receiving back on another, checking for validity.  Something we might use to exercise the uart-proxy application to verify it is not dropping traffic and catch regressions in that area.

Requires `make` and `gcc` are present on a system (originally built-and-tested on an Ubuntu 16.04 x64 VM).

### Usage
`Usage: ./port-runner -t <transmit device>,<baud> -r <receive device>,<baud> -f <data filename> -d <delay in ms between sends>`

### Examples

Passed all data correctly:
```
$ sudo ./port-runner -t /dev/ttyUSB0,b115200 -r /dev/ttyUSB1,b115200 -f foo -d 100
Loaded 174 bytes of data from 'foo', using a delay of 100 milliseconds between sends.
Sending traffic, press CTRL-C to stop : /dev/ttyUSB0 -> /dev/ttyUSB1.............^C

Results:
  Number of times data was sent: 10
  Good compares: 10
  Failed compares: 0
```

Failed on some data:
```
$ sudo ./port-runner -t /dev/ttyUSB0,b115200 -r /dev/ttyUSB1,b115200 -f foo -d 25
Loaded 174 bytes of data from 'foo', using a delay of 25 milliseconds between sends.
Sending traffic, press CTRL-C to stop : /dev/ttyUSB0 -> /dev/ttyUSB1..............................................................^C

Results:
  Number of times data was sent: 59
  Good compares: 24
  Failed compares: 51
```

Connection broken between TX and RX:
```
$ sudo ./port-runner -t /dev/ttyUSB0,b115200 -r /dev/ttyUSB1,b115200 -f foo -d 100
Loaded 174 bytes of data from 'foo', using a delay of 100 milliseconds between sends.
Sending traffic, press CTRL-C to stop : /dev/ttyUSB0 -> /dev/ttyUSB1.........................^C

Results:
  Number of times data was sent: 22
  Good compares: 0
  Failed compares: 0
```

### Ideas for improvements

* better recovery after miscompare (currently just 'reset' compare logic to the beginning of the expected buffer data)
* perhaps make RX thread blocking on reads
* support serial port flags/settings other than just baud rate
* support bi-directional testing (currently is just A -> B)
* support for verifying expected changes to data (i.e. uart-proxy modifies a MAC address)
