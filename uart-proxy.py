#!/usr/bin/env python3
#
# !!!POC!!!
#
# uart-proxy application for sniffing, replaying, and modifying
# UART data!
#
# Copyright 2020

import argparse
import serial
from serial.tools.list_ports import comports
import signal
import cmd

### Globals ###

# Port settings
portSettings = {}
portSettings["A"] = {"dev": "", "baud": 0}
portSettings["B"] = {"dev": "", "baud": 0}

# Delemiters for start-of-message and end-of-message, as provided via 'msgset' command.
msgDelims = {}
msgDelims["start"] = []
msgDelims["end"] = []

# Temp buffers for holding incoming (RX'd) data to check against msgDelims.
checkMsgBuffers = {}
checkMsgBuffers["A"] = []
checkMsgBuffers["B"] = []
checkMsgBufferMax = 0

# When capturing to an external file
captureFile = None
captureFileSize = 0
sniffRunning = False

### Methods ###

def signalHandler(signum, frame):
	global sniffRunning
	if signum == signal.SIGINT and sniffRunning:
		# Just stop sniffing...
		sniffRunning = False
	else:
		# Quit program...
		global captureFile
		if captureFile:
			captureFile.close()
		exit()

def welcomeBanner():
	print('''
##########################
Welcome to the UART Proxy!
##########################
	''')

# 'list' command, displays available serial ports.
def listSerialPorts(args = ''):
	if len(args) == 1 and args[0] == '-v':
		verbose = True
	else:
		verbose = False

	iterator = sorted(comports())
	# list ports
	for n, port_info in enumerate(iterator):
		print("{}".format(port_info.device))
		if verbose:
			print("    desc: {}".format(port_info.description))
			print("    hwid: {}".format(port_info.hwid))

# 'portget' command, allows user to dump current serial port settings in the app.
def portGet(args = ''):
	for p in ['A', 'B']:
		print('Port \'%s\': ' % (p), end ='')
		if portSettings[p]['dev']:
			print('device \'%s\' at %i' % (portSettings[p]['dev'], portSettings[p]['baud']))
		else:
			print('not set')

# 'portset' command, allows user to set serial port settings.
def portSet(args = ''):
	if len(args) != 3:
		print('Incorrect number of args, type \'help\' for usage')
		return
	port = args[0]
	deviceName = args[1]
	baud = args[2]
	if port != 'A' and port != 'B':
		print('Invalid \'port\' value, type \'help\' for usage')
		return

	# Dumb 'validation' of device and baud values: just try opening it and error if it didn't work!
	try:
		portTry = serial.Serial(deviceName, int(baud), timeout=0);
	except:
		print('Could not open device "%s" at baud "%s"' % (deviceName, baud));
		return

	# If we got here, it worked, so save off the values...
	portTry.close()
	portSettings[port]["dev"] = deviceName
	portSettings[port]["baud"] = int(baud)

# 'msgset' command, allows user to set start-of-message and -end-of-message delimiters.
def msgSet(args = ''):
	global msgDelims

	if len(args) < 2:
		print('Incorrect number of args, type \'help\' for usage')
		return
	settingType = args[0]
	valuesStr = " ".join(args[1:])
	values = valuesStr.split(",")
	if settingType != 'start' and settingType != 'end':
		print('Invalid \'start/end\' value, type \'help\' for usage')
		return
	msgDelims[settingType] = []
	for i in values:
		delim = []
		for j in i.split(" "):
			if len(j) > 0:
				delim.append(hex(int(j, 16)))
		msgDelims[settingType].append(delim)

def portSetApply():
	portSettingsMissing = []
	if not portSettings["A"]["dev"]:
		portSettingsMissing.append('A')
	if not portSettings["B"]["dev"]:
		portSettingsMissing.append('B')
	if len(portSettingsMissing) > 0:
		portStr = "' and '".join(portSettingsMissing)
		print('Port \'%s\' missing settings, please use the \'portset\' command to set device and baud.' % (portStr))
		return
	# Apply serial port settings and open ports.
	portA = serial.Serial(portSettings["A"]["dev"], portSettings["A"]["baud"], timeout=0);
	portB = serial.Serial(portSettings["B"]["dev"], portSettings["B"]["baud"], timeout=0);
	return portA, portB

# Check a received set of bytes for a match to a start-of-message or end-of-message delim.
#
# Return: matched string (delim) value (empty string if no match).
def checkMsg(port, startOrEnd, byte = None):
	global checkMsgBufferMax

	matchedStr = ""
	if checkMsgBufferMax > 0:
		if byte:
			if len(checkMsgBuffers[port]) == checkMsgBufferMax:
				# Our message buffer is full, remove the oldest char.
				checkMsgBuffers[port].pop(0)
			checkMsgBuffers[port].append(hex(byte))
		for i in msgDelims[startOrEnd]:
			cmpStartIndex = 0
			if len(checkMsgBuffers[port]) < len(i):
				# Not enough bytes in buffer to compare with delim pattern
				continue
			elif len(checkMsgBuffers[port]) > len(i):
				# Compare the correct length of the delim pattern to match on
				cmpStartIndex = len(checkMsgBuffers[port]) - len(i)
			if checkMsgBuffers[port][cmpStartIndex:] == i:
				# Matched a delimiter!
				checkMsgBuffers[port] = []
				matchedStr = i
				break
	return matchedStr

def tee(string = '', end = '\n'):
	global captureFileSize

	if captureFile:
		if len(string) > 0 and string[0] == '\b':
			# Need to erase some previously-written bytes due to a msg delimiter.
			if captureFileSize >= len(string):
				captureFileSize -= len(string)
			else:
				captureFileSize = 0
			captureFile.seek(captureFileSize, 0)
		else:
			captureFile.write('%s%s' % (string, end))
			captureFileSize += len(string) + len(end)
	print(string, end = end, flush = True)

# Sniffing traffic between two ports
def captureTraffic(args = ''):
	global captureFile
	global captureFileSize

	captureFile = None
	captureFileSize = 0
	if len(args) > 1:
		print('Incorrect number of args, type \'help\' for usage')
		return
	elif len(args) == 1:
		captureFileName = args[0]
		captureFile = open(captureFileName, "w")

	global checkMsgBufferMax
	checkMsgBufferMax = 0
	# Set checkMsgBufferMax to the 'longest' delimiter length.
	for i in msgDelims["start"] + msgDelims["end"]:
		if len(i) > checkMsgBufferMax:
			checkMsgBufferMax = len(i)

	portA, portB = portSetApply()

	print('Sniffing between ports \'%s\' <-> \'%s\'' % (portSettings["A"]["dev"], portSettings["B"]["dev"]), end = '')
	if captureFile:
		print(', saving captured traffic to \'%s\'' % captureFileName)
	else:
		print()
	print('Press CTRL-C to stop...')

	lastPrinted = 'None'
	matched = {}
	matched["A"] = {}
	matched["A"]["start"] = ""
	matched["A"]["end"] = ""
	matched["B"] = {}
	matched["B"]["start"] = ""
	matched["B"]["end"] = ""
	global sniffRunning
	sniffRunning = True
	while sniffRunning:

		# Process incoming data from port 'A'...
		try:
			dataA = portA.read(10)
		except serial.serialutil.SerialException:
			sniffRunning = False
			continue
		if len(dataA) > 0:
			if lastPrinted != 'A':
				# Last data we printed was from the other port, print our current port source.
				tee()
				tee('A -> B: ', '')
				lastPrinted = 'A'
			else:
				if len(matched["A"]["end"]) > 0:
					# The previous byte we looked at matched an end-of-message delim, go to new line.
					tee()
					tee('        ', '')
			matched["A"]["start"] = ""
			matched["A"]["end"] = ""
			for b in dataA:
				# Check if each incoming byte makes a start-of-message delim match.
				matched["A"]["start"] = checkMsg("A", "start", b)
				if len(matched["A"]["start"]) > 0:
					# We did match a start-of-message delim. 
					if len(matched["A"]["start"]) > 1:
						# It was a multi-byte start-of-message delim, so remove previous data bytes
						# that we had alrady printed.
						tee("\b" * 5 * (len(matched["A"]["start"]) - 1), '')
						tee(" " * 5 * (len(matched["A"]["start"]) - 1), '')
					tee()
					tee('        ' + " ".join(format("0x%02x" % int(n, 16)) for n in matched["A"]["start"]) + " ", '')
				else:
					# Data byte wasn't a start-of-message delim match, check if end-of-message delim..
					matched["A"]["end"] = checkMsg("A", "end")
					tee('0x%02x ' % b, '')
			# Send byte along to port B.
			portB.write(dataA)

		# Process incoming data from port 'B'...
		try:
			dataB = portB.read(10)
		except serial.serialutil.SerialException:
			sniffRunning = False
			continue
		if len(dataB) > 0:
			if lastPrinted != 'B':
				# Last data we printed was from the other port, print our current port source.
				tee()
				tee('B -> A: ', '')
				lastPrinted = 'B'
			else:
				if len(matched["B"]["end"]) > 0:
					# The previous byte we looked at matched an end-of-message delim, go to new line.
					tee()
					tee('        ', '')
			matched["B"]["start"] = ""
			matched["B"]["end"] = ""
			for b in dataB:
				# Check if each incoming byte makes a start-of-message delim match.
				matched["B"]["start"] = checkMsg("B", "start", b)
				if len(matched["B"]["start"]) > 0:
					# We did match a start-of-message delim. 
					if len(matched["B"]["start"]) > 1:
						# It was a multi-byte start-of-message delim, so remove previous data bytes
						# that we had alrady printed.
						tee("\b" * 5 * (len(matched["B"]["start"]) - 1), '')
						tee(" " * 5 * (len(matched["B"]["start"]) - 1), '')
					tee()
					tee('        ' + " ".join(format("0x%02x" % int(n, 16)) for n in matched["B"]["start"]) + " ", '')
				else:
					# Data byte wasn't a start-of-message delim match, check if end-of-message delim..
					matched["B"]["end"] = checkMsg("B", "end")
					tee('0x%02x ' % b, '')
			# Send byte along to port A.
			portA.write(dataB)
	portA.close()
	portB.close()
	if captureFile:
		captureFile.close()
		captureFile = None
		captureFileSize = 0
	print('\nCapture stopped\n\n')

# Dump capture file, along with line numbers
def dumpCapture(args = ''):
	if len(args) != 1:
		print('Incorrect number of args, type \'help\' for usage')
		return
	dumpFileName = args[0]
	# TODO errror handling
	dumpFile = open(dumpFileName, "r")
	dumpFileContents = dumpFile.readlines()

	lineNum = 1
	for line in dumpFileContents:
		print('%5u: %s' % (lineNum, line.rstrip()))
		lineNum += 1

# Replaying traffic between two ports
def replayTraffic(args = ''):
	if len(args) == 0 or len(args) > 2:
		print('Incorrect number of args, type \'help\' for usage')
		return
	replayFileName = args[0]
	replayFile = open(replayFileName, "r")
	# TODO errror handling
	replayFileContents = replayFile.readlines()

	lines = []
	if len(args) == 2:
		valuesStr = " ".join(args[1:])
		values = valuesStr.split(",")
		for i in values:
			hyphenPos = i.find('-')
			if hyphenPos > 0:
				rangeStart = int(i[0:hyphenPos])
				rangeEnd = int(i[hyphenPos+1:]) + 1
				lines.extend(list(range(rangeStart, rangeEnd)))
			else:
				lines.append(int(i))
	else:
		lines = list(range(1,len(replayFileContents) + 1))

	# Apply serial port settings
	portA, portB = portSetApply()

	# Replay user-specfied traffic
	lineNum = 1
	direction = "unknown"
	for line in replayFileContents:
		startIndex = 0
		if line.find("A -> B") == 0 or line.find("B -> A") == 0:
			startIndex = line.find(':') + 1
			direction = line[0:startIndex - 1]
		if lineNum in lines:
			if direction == "unknown":
				print('Could not detect the direction to send replay data, skipping line %d...' % (lineNum))
			else:
				lineData = list(map(lambda b: int(b, 16), line[startIndex:].rstrip().split()))
				print('%s: %s' % (direction, line[startIndex:].rstrip()))
				if direction == "A -> B":
					portB.write(lineData)
				else:
					portA.write(lineData)
		lineNum += 1


class repl(cmd.Cmd):
	prompt = '> '
	use_rawinput = True

	def do_list(self, arg):
		'''
Description: list all serial ports available to use

Usage: list [-v]
		'''
		listSerialPorts(arg.split())

	def do_portget(self, arg):
		'''
Description: dump current UART port settings

Usage: portget
		'''
		portGet(arg.split())

	def do_portset(self, arg):
		'''
Description: apply UART port settings

Usage: portset <A|B> <device> <baud>

Example(s): portset A /dev/ttyUSB0 115200
            portset B /dev/ttyUSB0 115200
		'''
		portSet(arg.split())

	def do_msgset(self, arg):
		'''
Description: apply message parsing settings

Usage:	msgset <start|end> <hex byte pattern>[,<hex byte pattern>,...]

Example(s): msgset start 0x01 0x00, 0x01 0x04, 0x07
            msgset end 0x99
		'''
		msgSet(arg.split())

	def do_capture(self, arg):
		'''
Description: start forwarding-and-capturing UART traffic

Usage:	capture [output file]

Example(s): capture
            capture sniffed.out
		'''
		captureTraffic(arg.split())

	def do_dump(self, arg):
		'''
Description: dump capture file contents

Usage: dump <capture file>

Example(s): dump sniffed.out
		'''
		dumpCapture(arg.split())

	def do_replay(self, arg):
		'''
Description: start replaying-and-forwarding UART traffic

Usage: replay <capture file> [line number(s) to replay]

Example(s): replay sniffed.out
            replay sniffed.out 1,4
            replay sniffed.out 2-10
		'''
		replayTraffic(arg.split())

	def do_exit(self, arg):
		quit()

	def do_quit(self, arg):
		quit()

############################
# main!
############################
def main():

	# Setup command line arg parsing.
	argParser = argparse.ArgumentParser(description = 'UART Proxy app')
	argParser.add_argument('-l', action = 'store_true', dest = 'listPorts',
		help = 'list all serial ports available to use')
	argParser.add_argument('-b', action = 'store_true', dest = 'background',
		help = 'background the app for use with web browser UI (TBD)')
	argParser.add_argument('-q', action = 'store_true', dest = 'quiet',
		help = 'skip the banner on startup')
	argParser.add_argument('-v', '--verbose', action='store_true',
		help='show more information')

	# Parse (and action on) the command line args...
	cmdlineArgs = argParser.parse_args()

	if cmdlineArgs.listPorts:
		args = []
		if cmdlineArgs.verbose:
			args.append('-v')
		listSerialPorts(args)
		return

	if cmdlineArgs.background:
		print("Background logic is TBD, running in interactive mode...")
	
	if not cmdlineArgs.quiet:
		welcomeBanner()

	# Setup signal hanlding we need to do.
	signal.signal(signal.SIGINT, signalHandler)

	# "interactive prompt" (a.k.a. REPL).
	repl().cmdloop()

if __name__ == "__main__":
	main()
