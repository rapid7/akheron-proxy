# Test tools

## port-runner
Simple C program for transmitting traffic out one serial port and receiving back on another, checking for validity.

Requires `make` and `gcc` are present on a system (originally built-and-tested on an Ubuntu 16.04 x64 VM).

### Usage
`Usage: ./port-runner -t <transmit device> -r <receive device> -f <data filename> -d <delay in ms between sends>`

### Examples
```
$ sudo ./port-runner -t /dev/ttyUSB0,B115200 -r /dev/ttyUSB1 -f qwe -d 100
Loaded 4 bytes of data from 'qwe', leaving 100 milliseconds between sends...
Sending traffic.................................................................................^C

Done.

Data sent 78 times, failed compares: 0
```

```
$ sudo ./port-runner -t /dev/ttyUSB0,b115200 -r /dev/ttyUSB1,b115200 -f foo -d 100
Loaded 174 bytes of data from 'foo', leaving 100 milliseconds between sends...
Sending traffic...................................................^C

Done.

Data sent 48 times, failed compares: 0
```
