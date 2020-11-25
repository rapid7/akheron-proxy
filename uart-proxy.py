#!/usr/bin/env python3
#
# !!!POC!!!
#
# uart-proxy application for capturing, replaying, and modifying
# UART data!
#
# Copyright 2020

try:
	import argparse
	import serial
	from serial.tools.list_ports import comports
	import signal
	import cmd
	import serial_processor
	import threading
	from time import sleep
	from enum import Enum, auto
	import functools
	import operator
except ImportError as e:
	print("Error on module import: %s" % (str(e)))
	exit()


class SupportedChecksums(Enum):
	Checksum8Xor            = auto()
	Checksum8Modulo256      = auto()
	Checksum8Modulo256Plus1 = auto()
	Checksum82sComplement   = auto()


### Globals ###
version = "0.1"

# Port settings, as provided via the 'portset' command.
portSettings = {}
portSettings["A"] = {"dev": "", "baud": 0}
portSettings["B"] = {"dev": "", "baud": 0}

# Delemiters for start-of-message and end-of-message, as provided via 'delimset' command.
msgDelims = {}
msgDelims["start"] = []
msgDelims["end"] = []
delimMatching = False

# Pattern replacement/substitution, as provided via the 'replaceset' command.
replacePatterns = {}
replacePatterns["A"] = {}
replacePatterns["B"] = {}

# Pattern replacement/substitution checksum recalculation method, as provided via the 'checksumset' command.
replaceChecksums = {
	"A": None,
	"B": None
}

# Temp buffers for holding incoming (RX'd) data to check against msgDelims.
checkMsgBuffers = {}
checkMsgBuffers["A"] = []
checkMsgBuffers["B"] = []
checkMsgBufferMax = 0

# When capturing to an external file
captureFile = None
captureFileSize = 0
trafficPassing = False
watching = False

# Resource locks
writerLock = {}
writerLock["A"] = threading.Lock()
writerLock["B"] = threading.Lock()
teeLock = threading.Lock()

### Methods ###

# Handle signals the program receives.
# Returns: n/a
def signalHandler(signum, frame):
	if signum == signal.SIGINT:
		global watching
		if watching:
			# stop watching
			watching = False
			print("\nWatch mode exited.")
		else:
			# CTRL-C was received
			# Quit program...
			quit_app()

# Banner displayed at startup.
# Returns: n/a
def welcomeBanner():
	print('''
##########################
Welcome to the UART Proxy!
          v%s
##########################
	''' % (version))

# 'list' command, displays available serial ports.
# args:
#   '-v': enable verbose listing of more details
# Returns: n/a
def listSerialPorts(args = ""):
	if len(args) == 1 and args[0] == "-v":
		verbose = True
	else:
		verbose = False

	iterator = sorted(comports())
	for n, port_info in enumerate(iterator):
		print("{}".format(port_info.device))
		if verbose:
			print("    desc: {}".format(port_info.description))
			print("    hwid: {}".format(port_info.hwid))

# 'portget' command, allows user to dump current serial port settings in the app.
# args: n/a
# Returns: n/a
def portGet(args = ""):
	for p in ["A", "B"]:
		print("Port \"%s\": " % (p), end ="")
		if portSettings[p]["dev"]:
			print("device \"%s\" at %i" % (portSettings[p]["dev"], portSettings[p]["baud"]), end = "")
		print()

# 'portset' command, allows user to set serial port settings.
# args:
#   [0]: specifies port ("A" or "B") being set
#   [1]: specifies the serial device name  (e.g. "/dev/ttyUSB0")
#   [2]: specifies the baud speed (e.g. 115200)
# Returns: n/a
def portSet(args = ""):
	if len(args) != 3:
		print("Incorrect number of args, type \"help\" for usage")
		return
	port = args[0]
	deviceName = args[1]
	baud = args[2]
	if port != "A" and port != "B":
		print("Invalid \"port\" value, type \"help\" for usage")
		return

	if trafficPassing:
		print("Cannot change port settings while passing traffic, please \"stop\" first")
		return

	# Dumb 'validation' of device and baud values: just try opening it and error if it didn't work!
	try:
		portTry = serial.Serial(deviceName, int(baud), timeout=0);
	except serial.SerialException as e:
		print("Could not open device \"%s\" at baud \"%s\": %s" % (deviceName, baud, str(e)));
		return

	# If we got here, it worked, so save off the values...
	portTry.close()

	portSettings[port]["dev"] = deviceName
	portSettings[port]["baud"] = int(baud)

	# Warn if we're setting the port to the same device as the other port, as that's likely not wanted...
	if port == "A":
		otherPort = "B"
	else:
		otherPort = "A"
	if portSettings[port]["dev"] == portSettings[otherPort]["dev"]:
		print("WARNING: both port \"A\" and \"B\" are set to device %s, YOU PROBABLY DON'T WANT THIS." % (portSettings[port]["dev"]))

# 'delimget' command, allows user to dump current start-of-message and end-of-message delimeters.
# Returns: n/a
def delimGet(args = ""):
	for d in ["start", "end"]:
		print("%5s delimiters: " % (d), end ="")
		if msgDelims[d]:
			for e in msgDelims[d]:
				print(" ".join(format("0x%02x" % int(n, 16)) for n in e) + ", ", end = "")
			print("\b\b ", end = "")
		print()

# 'delimset' command, allows user to set start-of-message and end-of-message delimiters.
# args:
#   [0]: specifies type of message delimiter ("start" or "end") being set
#   [1]: specifies the value(s) to be considered delimeters
#        - values separated by spaces are considered a sequence
#        - commas denote separate delimiters
# Returns: n/a
def delimSet(args = ""):
	global msgDelims

	if len(args) < 1:
		print("Incorrect number of args, type \"help\" for usage")
		return

	if trafficPassing:
		print("Cannot change message demlims while passing traffic, please \"stop\" first")
		return

	settingType = args[0]
	valuesStr = " ".join(args[1:])
	values = valuesStr.split(",")
	if settingType != "start" and settingType != "end":
		print("Invalid \"start/end\" value, type \"help\" for usage")
		return
	msgDelims[settingType] = []
	for i in values:
		delim = []
		for j in i.split(" "):
			if len(j) > 0:
				delim.append(hex(int(j, 16)))
		msgDelims[settingType].append(delim)

# Apply serial port device settings before executing sniffing/replay operations.
# Returns: Serial objects for open ports "A" and "B"
def portSetApply():
	portSettingsMissing = []
	for p in ["A", "B"]:
		if not portSettings[p]["dev"]:
			portSettingsMissing.append(p)
	if len(portSettingsMissing) > 0:
		portStr = "\" and \"".join(portSettingsMissing)
		print("Port \"%s\" missing settings, please use the \"portset\" command to set device and baud." % (portStr))
		return False

	# Apply serial port settings and open ports.
	port = {}
	for p in ["A", "B"]:
		try:
			port[p] = serial.Serial(portSettings[p]["dev"], portSettings[p]["baud"], timeout=0);
		except serial.SerialException as e:
			print("Could not open device \"%s\": %s" % (portSettings[p]["dev"], str(e)));
			if p == "B":
				port["A"].close()
			return False
	# NOTE: close these and retrunt boolean
	for p in ["A", "B"]:
		port[p].close()
	return True

# 'replaceget' command, allows user to dump current "substitute pattern-X-for-Y" values.
# Returns: n/a
def replaceGet(args = ""):
	for p in ["A", "B"]:
		print("Replace port %c pattern X -> pattern Y:" % p)
		for r in replacePatterns[p]:
			print("  %s -> %s" % (str(r), str(" ".join(replacePatterns[p][r]))))

# 'replaceset' command, allows user to set "substitute pattern-X-for-Y" values.
# args:
#   [0]: specifies the port's ("A" or "B") traffic to apply these pattern replacements on
#   [1]: specifies the patterns to be replaces/swapped/substituted
#        - values separated by spaces are considered a sequence
#        - "arrow" (i.e. "->") denotes pattern X (left-hand side) should be swapped for Y (RHS)
#        - commas denote separate "substitute pattern-X-for-Y" pairs
# Returns: n/a
def replaceSet(args = ""):
	global replacePatterns

	if len(args) < 1:
		print("Incorrect number of args, type \"help\" for usage")
		return
	port = args[0]
	valuesStr = " ".join(args[1:])
	values = valuesStr.split(",")
	if port != "A" and port != "B":
		print("Invalid \"port\" value, type \"help\" for usage")
		return
	replacePatterns[port] = {}
	for i in values:
		if len(i) == 0:
			continue
		lhsRhsList = i.split("->")
		if len(lhsRhsList) != 2:
			print("Invalid replace pattern provided, skipping \"%s\"" % i)
			continue
		if len(lhsRhsList[0]) == 0 or len(lhsRhsList[1]) == 0:
			print("Invalid replace pattern provided, skipping \"%s\"" % i)
			continue
		pattern = {}
		index = 0
		for p in ["LHS", "RHS"]:
			pattern[p] = []
			for k in lhsRhsList[index].split(" "):
				if len(k) > 0:
					pattern[p].append(hex(int(k, 16)))
			index += 1
		replacePatterns[port][" ".join(pattern["LHS"])] = pattern["RHS"]

# 'checksumget' command, allows user to output the current checksum recalculation used after pattern replacements
# Returns: n/a
def checksumGet(args = ""):
	for p in ["A", "B"]:
		if replaceChecksums[p]:
			print(f"Replace on port {p} using checksum '{replaceChecksums[p].name}'")
		else:
			print(f"No replace checksum specified on port {p}")

# 'checksumset' command, allows user to set checksum recalculation used after pattern replacements
# args:
#   [0]: specifies the port's ("A" or "B") traffic to apply the checksum recalculation during pattern replacements
#   [1]: specifies the integer value or name of the checksum
# Returns: n/a
def checksumSet(args = ""):
	global replaceChecksums

	if len(args) < 1:
		print("Incorrect number of args, type \"help\" for usage")
		return
	port = args[0]
	if port != "A" and port != "B":
		print("Invalid \"port\" value, type \"help\" for usage")
		return

	if len(args) < 2:
		replaceChecksums[port] = None
	else:
		try:
			try:
				replaceChecksums[port] = SupportedChecksums(int(args[1]))
			except ValueError:
				replaceChecksums[port] = SupportedChecksums[args[1]]
		except (ValueError, KeyError):
			print("Invalid checksum specified. Supported checksums:")
			for checksum in SupportedChecksums:
				print(f"{checksum.value}: {checksum.name}")
	return

def replacePatternsIfMatched(data, patterns, checksumMethod):
	if len(patterns) == 0:
		# No patterns to match on, we're done
		return data
	for k,v in patterns.items():
		kList = k.split(" ")
		matchList = [int(i, 16) for i in kList]
		lenML = len(matchList)
		for i in range(len(data)-lenML + 1):
			if matchList == data[i:i + lenML]:
				data[i:i + lenML] = [int(val, 16) for val in v]
				checksum = calculateChecksum(data[:-1], checksumMethod)
				if checksum is not None:
					data[-1] = checksum
				break
	return data

def calculateChecksum(data, checksumMethod):
	if checksumMethod is None:
		# No checksum specified
		return None

	value = 0
	if checksumMethod == SupportedChecksums.Checksum8Xor:
		value = functools.reduce(operator.xor, data)
	elif checksumMethod == SupportedChecksums.Checksum8Modulo256:
		value = sum(data) % 256
	elif checksumMethod == SupportedChecksums.Checksum8Modulo256Plus1:
		value = (sum(data) % 256) + 1
	elif checksumMethod == SupportedChecksums.Checksum82sComplement:
		value = -(sum(data) % 256) & 0xFF

	return value

# Check a received set of bytes for a match to a start-of-message or end-of-message delim.
# port: indicates which port ("A" or "B") delimiters should be used for this check
# startOrEnd: indicates if the "start" or "end" message delimiters should be checked.
# byte: new byte of data received
# Returns: matched string (delim) value OR an empty string if no match
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

# Similar to the *nix command 'tee', this method sends output to both the display
#   and capture file, if in use.
# string: string value to display+write
# end: trailing character for 'string'
# Returns: n/a
def tee(string = "", end = "\n"):
	with teeLock:
		global captureFileSize

		if captureFile:
			if len(string) > 0 and string[0] == "\b":
				# Need to erase some previously-written bytes due to a msg delimiter.
				if captureFileSize >= len(string):
					captureFileSize -= len(string)
				else:
					captureFileSize = 0
				captureFile.seek(captureFileSize, 0)
			else:
				captureFile.write("%s%s" % (string, end))
				captureFile.flush()
				captureFileSize += len(string) + len(end)

		if watching:
			print(string, end = end, flush = True)

# Capturing traffic between two ports.
# args:
#   [0]: filename to write captured data to
# Returns: n/a
def captureTrafficStart(args = ""):
	global replacePatterns
	global captureFile
	global captureFileSize

	if len(args) != 1:
		print("Incorrect number of args, type \"help\" for usage")
		return

	if captureFile:
		print("A capture is already running, type \"capturestop\" to stop")
		return

	captureFile = None
	captureFileSize = 0
	captureFileName = args[0]
	try:
		captureFile = open(captureFileName, "w")
	except IOError as e:
		print("File \"%s\" could not be opened: %s" % (captureFileName, str(e)))
		return

	print("Saving captured traffic to \"%s\"..." % captureFileName)

# Capturing traffic between two ports.
# args:
#   [0]: filename to write captured data to
# Returns: n/a
def captureTrafficStop(args = ""):
	global captureFile
	global captureFileSize

	# Close ports and capture file, if applicable.
	if captureFile:
		captureFile.close()
		captureFile = None
		captureFileSize = 0
		print("Capture stopped")


# Dump capture file, along with line numbers.
# args:
#   [0]: filename to dump captured data from
# Returns: n/a
def dumpCapture(args = ""):
	if len(args) != 1:
		print("Incorrect number of args, type \"help\" for usage")
		return
	dumpFileName = args[0]

	try:
		dumpFile = open(dumpFileName, "r")
	except IOError as e:
		print("File \"%s\" could not be opened: %s" % (dumpFileName, str(e)))
		return
	dumpFileContents = dumpFile.readlines()

	lineNum = 1
	for line in dumpFileContents:
		print("%5u: %s" % (lineNum, line.rstrip()))
		lineNum += 1

# Replaying traffic between two ports.
# args:
#   [0]: filename to replay captured data from
#   [1]: line(s) of the replay file of the data to be replayed, commas and hyphens supported (OPTIONAL)
# Returns: n/a
def replayTraffic(args = ""):
	if len(args) == 0 or len(args) > 2:
		print("Incorrect number of args, type \"help\" for usage")
		return
	replayFileName = args[0]
	try:
		replayFile = open(replayFileName, "r")
	except IOError as e:
		print("File \"%s\" could not be opened: %s" % (replayFileName, str(e)))
		return
	replayFileContents = replayFile.readlines()

	lines = []
	if len(args) == 2:
		valuesStr = " ".join(args[1:])
		values = valuesStr.split(",")
		for i in values:
			hyphenPos = i.find("-")
			if hyphenPos > 0:
				rangeStart = int(i[0:hyphenPos])
				rangeEnd = int(i[hyphenPos+1:]) + 1
				lines.extend(list(range(rangeStart, rangeEnd)))
			else:
				lines.append(int(i))
	else:
		lines = list(range(1,len(replayFileContents) + 1))

	# Apply serial port settings
	if not portSetApply():
		# Port settings not valid...
		return

	# Replay user-specified traffic
	lineNum = 1
	direction = "unknown"
	# Make an initial pass to determine which direction we'll limit replay to...
	for line in replayFileContents:
		if line.find("A -> B") == 0 or line.find("B -> A") == 0:
			direction = line[0:line.find(":")]
		if lineNum in lines:
			break;
	if direction == "unknown":
		print("Could not detect the direction to send replay data, make sure your capture file and line selection are valid")
		return

	if direction == "A -> B":
		p = "A"
		outp = "B"
		outDevID = serial_processor.DeviceIdentifier.BETA
	else:
		p = "B"
		outp = "A"
		outDevID = serial_processor.DeviceIdentifier.ALPHA

	# Acquire lock for writing to the "output port"
	with writerLock[outp]:
		print("Replaying data from %s, press CTRL-C to exit watch mode..." % direction, end="")
		global watching
		watching = True
		for line in replayFileContents:
			startIndex = 0
			if line.find("A -> B") == 0 or line.find("B -> A") == 0:
				startIndex = line.find(":") + 1
				currDirection = line[0:startIndex - 1]
			if lineNum in lines and currDirection == direction:
				lineData = list(map(lambda b: int(b, 16), line[startIndex:].rstrip().split()))
				lineData = replacePatternsIfMatched(lineData, replacePatterns[p], replaceChecksums[p])
				#print("%s: %s" % (direction, " ".join(format("0x%02x" % int(n)) for n in lineData) + " "))
				processor.write(outDevID, bytes(lineData))
				tee("\n%s: %s" % (direction, " ".join(format("0x%02x" % int(n)) for n in lineData) + " "), "")
			lineNum += 1
		tee()
	watchWaitExit()

def dataReceivedCallbackA(data):
	#print("PJB: callbackA, data = %s, type %s" % (str(data), str(type(data))))
	dataReceivedCallback(data, "A")
	return data

def dataReceivedCallbackB(data):
	#print("PJB: callbackB, data = %s, type %s" % (str(data), str(type(data))))
	dataReceivedCallback(list(data), "B")
	return data

lastPrinted = "None"
portDataOutBuffer = {}
delimMatched = {}
portDataOutBuffer = {}
bytesOnLine = 0
def dataReceivedCallback(data, p):
	# When matching on start/stop message delimters, we'll buffer the data in case
	# there are replacements/substitutions to make...
	global delimMatched
	global lastPrinted
	global portDataOutBuffer
	global bytesOnLine

	# Alternate reading data from each port in the connection...
	if p == "A":
		outp = "B"
		outDevID = serial_processor.DeviceIdentifier.BETA
	else:
		outp = "A"
		outDevID = serial_processor.DeviceIdentifier.ALPHA

	# Acquire lock for writing to the "output port"
	with writerLock[outp]:
		if len(data) > 0:
			if lastPrinted != p:
				# Last data we printed was from the other port, print our current port source.
				if lastPrinted != "None":
					tee()
				tee("%c -> %c: " % (p, outp), "")
				lastPrinted = p
				bytesOnLine = 0
			else:
				if len(delimMatched[p]["end"]) > 0:
					# The previous byte we looked at matched an end-of-message delim, go to new line.
					tee()
					tee("        ", "")
					bytesOnLine = 0
			delimMatched[p]["start"] = ""
			delimMatched[p]["end"] = ""
			for b in data:
				# Check if each incoming byte makes a start-of-message delim match.
				delimMatched[p]["start"] = checkMsg(p, "start", b)
				if len(delimMatched[p]["start"]) > 0:
					portDataOutBuffer[outp].append(b)
					# We did match a start-of-message delim. 
					if len(delimMatched[p]["start"]) > 1:
						# It was a multi-byte start-of-message delim, so remove previous data bytes
						# that we had alrady printed.
						tee("\b" * 5 * (len(delimMatched[p]["start"]) - 1), "")
					if bytesOnLine >= len(delimMatched[p]["start"]):
						# Need to erase and go to a new line now (also indent!)
						tee(" " * 5 * (len(delimMatched[p]["start"]) - 1), "")
						tee()
						tee("        ", "")
					tee(" ".join(format("0x%02x" % int(n, 16)) for n in delimMatched[p]["start"]) + " ", "")
					bytesOnLine = len(delimMatched[p]["start"])
					# Send the buffered message out the correct port and reset the databuffer...
					lastDataIndex = len(portDataOutBuffer[outp]) - len(delimMatched[p]["start"])
					processor.write(outDevID, bytes(portDataOutBuffer[outp][:lastDataIndex]))
					portDataOutBuffer[outp] = [int(n, 16) for n in delimMatched[p]["start"]]
				else:
					# Data byte wasn't a start-of-message delim match, check if end-of-message delim...
					delimMatched[p]["end"] = checkMsg(p, "end")
					tee("0x%02x " % b, "")
					bytesOnLine += 1
					if delimMatching:
						portDataOutBuffer[outp].append(b)
					if len(delimMatched[p]["end"]) > 0:
						# Send the buffered message out the correct port and reset the databuffer...
						processor.write(outDevID, bytes(portDataOutBuffer[outp]))
						portDataOutBuffer[outp] = []
				if not delimMatching:
					# Send byte along to the other port now...
					processor.write(outDevID, (b).to_bytes(1, byteorder='big'))


processor = None

# Start traffic between two ports.
# args: none
# Returns: n/a
def startTraffic(args = ""):
	global checkMsgBufferMax
	checkMsgBufferMax = 0
	global delimMatching
	delimMatching = False

	# Set checkMsgBufferMax to the 'longest' delimiter length.
	for i in msgDelims["start"] + msgDelims["end"]:
		delimMatching = True
		if len(i) > checkMsgBufferMax:
			checkMsgBufferMax = len(i)

	# Verify the ports and port settings are valid...
	port = {}
	if not portSetApply():
		# Something failed in our open+settings attempt, bail out...
		return

	global portDataOutBuffer
	if delimMatching:
		portDataOutBuffer = {}

	global delimMatched
	delimMatched = {}
	for p in ["A", "B"]:
		delimMatched[p] = {}
		delimMatched[p]["start"] = ""
		delimMatched[p]["end"] = ""
		if delimMatching:
			portDataOutBuffer[p] = []

	conf_a = {
		'device': portSettings["A"]["dev"],
		'baudrate': portSettings["A"]["baud"],
		'parity': serial.PARITY_NONE,
		'stopbits': serial.STOPBITS_ONE,
		'bytesize': serial.EIGHTBITS,
		'timeout': 1,
		'pass_through': False,
		'data_received_callback': dataReceivedCallbackA
	}
	conf_b = {
		'device': portSettings["B"]["dev"],
		'baudrate': portSettings["B"]["baud"],
		'parity': serial.PARITY_NONE,
		'stopbits': serial.STOPBITS_ONE,
		'bytesize': serial.EIGHTBITS,
		'timeout': 1,
		'pass_through': False,
		'data_received_callback': dataReceivedCallbackB
	}

	global processor
	processor = serial_processor.SerialProcessor(conf_a, conf_b)
	processor.start()

	global trafficPassing
	trafficPassing = True
	print("Data now PASSING between ports \"%s\" <-> \"%s\"..." % (portSettings["A"]["dev"], portSettings["B"]["dev"]))
	return

# Start traffic between two ports.
# args: none
# Returns: n/a
def stopTraffic(args = ""):
	global trafficPassing
	trafficPassing = False

	if processor:
		processor.stop()
		print("Data now BLOCKED between ports \"%s\" <-> \"%s\"." % (portSettings["A"]["dev"], portSettings["B"]["dev"]))
	return

def watchWaitExit():
	while watching:
		sleep(.25)

def watch(args = ""):
	if not trafficPassing:
		print("Data is not currently being passed between ports; run 'start' command first.")
		return

	global watching
	print("Watching data passed between ports. Press CTRL-C to stop...")
	watching = True

def quit_app():
	if captureFile:
		# Close our exisitng capture...
		captureFile.close()
	if processor:
		# Cleanup serial port threads...
		processor.stop()
	quit()

# Implementation of our REPL functionality.
class repl(cmd.Cmd):
	prompt = "> "
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
            portset B /dev/ttyUSB1 115200
		'''
		portSet(arg.split())

	def do_delimget(self, arg):
		'''
Description: dump current message start/end delimiter settings

Usage: delimget
		'''
		delimGet(arg.split())

	def do_delimset(self, arg):
		'''
Description: apply message parsing settings

Usage:	delimset <start|end> <hex byte pattern>[,<hex byte pattern>,...]

Example(s): delimset start 0x01 0x00, 0x01 0x04, 0x07
            delimset end 0x99
		'''
		delimSet(arg.split())

	def do_replaceget(self, arg):
		'''
Description: dump current message pattern replace/substitute settings

Usage: replaceget
		'''
		replaceGet(arg.split())

	def do_replaceset(self, arg):
		'''
Description: apply message pattern replace/substitute settings

Usage:	replaceset <A|B> <hex byte pattern to match on> -> <hex byte pattern to replace with>[,<hex byte pattern to match on>,...]

Example(s): replaceset A 0x31 -> 0x32
            replaceset A 0x31 0x32 0x33 -> 0x21 0x22 0x23, 0x45 0x46 -> 0x55
		'''
		replaceSet(arg.split())

	def do_checksumget(self, arg):
		'''
Description: output the current checksum recalculation used after message pattern replacement

Usage: checksumget
		'''
		checksumGet(arg.split())

	def do_checksumset(self, arg):
		'''
Description: set checksum recalculation used after message pattern replacement.
Note: This should be used with start delim patterns since the computed
checksum will be placed at the end of the message.

Usage:	checksumset <A|B> <checksum number or name>

Available Checksums:
  1: Checksum8Xor
  2: Checksum8Modulo256
  3: Checksum8Modulo256Plus1
  4: Checksum82sComplement

Example(s): checksumset A 1
            checksumset B Checksum8Modulo256
		'''
		checksumSet(arg.split())

	def do_capturestart(self, arg):
		'''
Description: start capturing UART traffic

Usage:	capturestart <output capture file>

Example(s): capturestart
            capturestart sniffed.out
		'''
		captureTrafficStart(arg.split())

	def do_capturestop(self, arg):
		'''
Description: stop capturing UART traffic

Usage:	capturestop

Example(s): capturestop
            capturestop sniffed.out
		'''
		captureTrafficStop(arg.split())

	def do_capturedump(self, arg):
		'''
Description: dump capture file contents

Usage: capturedump <capture file>

Example(s): capturedump sniffed.out
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

	def do_start(self, arg):
		'''
Description: start forwarding UART traffic

Usage:	start

Example(s): start
		'''
		startTraffic(arg.split())

	def do_stop(self, arg):
		'''
Description: stop forwarding UART traffic

Usage:	stop

Example(s): stop
		'''
		stopTraffic(arg.split())

	def do_watch(self, arg):
		'''
Description: watch UART traffic

Usage:	watch
		'''
		watch(arg.split())
		watchWaitExit()

	def do_version(self, arg):
		print("v%s" % (version))

	def do_exit(self, arg):
		quit_app()

	def do_quit(self, arg):
		quit_app()

	def emptyline(self):
		pass

############################
# main!
############################
def main():

	# Setup command line arg parsing.
	argParser = argparse.ArgumentParser(description = "UART Proxy app")
	argParser.add_argument("-l", action = "store_true", dest = "listPorts",
		help = "list all serial ports available to use")
	argParser.add_argument("-b", action = "store_true", dest = "background",
		help = "background the app for use with web browser UI (TBD)")
	argParser.add_argument("-q", action = "store_true", dest = "quiet",
		help = "skip the banner on startup")
	argParser.add_argument("-V", "--version", action="store_true", dest = "version",
		help="show version information")
	argParser.add_argument("-v", "--verbose", action="store_true",
		help="show more information")


	# Parse (and action on) the command line args...
	cmdlineArgs = argParser.parse_args()

	if cmdlineArgs.listPorts:
		args = []
		if cmdlineArgs.verbose:
			args.append("-v")
		listSerialPorts(args)
		return

	if cmdlineArgs.version:
		print("v%s" % (version))
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
