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
except ImportError as e:
	print("Error on module import: %s" % (str(e)))
	exit()

### Globals ###
version = "0.1"

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

# Handle signals the program receives.
# Returns: n/a
def signalHandler(signum, frame):
	global sniffRunning

	if signum == signal.SIGINT:
		# CTRL-C was received
		if sniffRunning:
			# Just stop sniffing...
			sniffRunning = False
		else:
			# Quit program...
			global captureFile
			if captureFile:
				captureFile.close()
			exit()

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

# 'msgget' command, allows user to dump current start-of-message and end-of-message delimeters.
# Returns: n/a
def msgGet(args = ""):
	for d in ["start", "end"]:
		print("%5s delimiters: " % (d), end ="")
		if msgDelims[d]:
			for e in msgDelims[d]:
				print(" ".join(format("0x%02x" % int(n, 16)) for n in e) + ", ", end = "")
			print("\b\b ", end = "")
		print()

# 'msgset' command, allows user to set start-of-message and end-of-message delimiters.
# args:
#   [0]: specifies type of message delimiter ("start" or "end") being set
#   [1]: specifies the value(s) to be considered delimeters
#        (values separated by spaces are considered a sequence, commas denote separate delimiters)
# Returns: n/a
def msgSet(args = ""):
	global msgDelims

	if len(args) < 1:
		print("Incorrect number of args, type \"help\" for usage")
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
		return None, None

	# Apply serial port settings and open ports.
	port = {}
	for p in ["A", "B"]:
		try:
			port[p] = serial.Serial(portSettings[p]["dev"], portSettings[p]["baud"], timeout=0);
		except serial.SerialException as e:
			print("Could not open device \"%s\": %s" % (portSettings[p]["dev"], str(e)));
			return None, None
	return port["A"], port["B"]

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
			captureFileSize += len(string) + len(end)
	print(string, end = end, flush = True)

# Sniffing traffic between two ports.
# args:
#   [0]: filename to write captured data to (OPTIONAL)
# Returns: n/a
def captureTraffic(args = ""):
	global captureFile
	global captureFileSize

	captureFile = None
	captureFileSize = 0
	if len(args) > 1:
		print("Incorrect number of args, type \"help\" for usage")
		return
	elif len(args) == 1:
		captureFileName = args[0]
		try:
			captureFile = open(captureFileName, "w")
		except IOError as e:
			print("File \"%s\" could not be opened: %s" % (captureFileName, str(e)))
			return

	global checkMsgBufferMax
	checkMsgBufferMax = 0
	# Set checkMsgBufferMax to the 'longest' delimiter length.
	for i in msgDelims["start"] + msgDelims["end"]:
		if len(i) > checkMsgBufferMax:
			checkMsgBufferMax = len(i)

	# Open the ports and apply the settings...
	port = {}
	port["A"], port["B"] = portSetApply()
	if not port["A"]:
		# Something failed in our open+settings attempt, bail out...
		return

	print("Sniffing between ports \"%s\" <-> \"%s\"" % (portSettings["A"]["dev"], portSettings["B"]["dev"]), end = "")
	if captureFile:
		print(", saving captured traffic to \"%s\"" % captureFileName)
	else:
		print()
	print("Press CTRL-C to stop...")
	print()

	lastPrinted = "None"
	matched = {}
	for p in ["A", "B"]:
		matched[p] = {}
		matched[p]["start"] = ""
		matched[p]["end"] = ""
	global sniffRunning
	sniffRunning = True
	while sniffRunning:
		# Alternate reading data from each port in the connection...
		for p in ["A", "B"]:
			if p == "A":
				outp = "B"
			else:
				outp = "A"
			# Process incoming data from port 'p'...
			try:
				data = port[p].read(10)
			except serial.serialutil.SerialException:
				sniffRunning = False
				continue
			if len(data) > 0:
				if lastPrinted != p:
					# Last data we printed was from the other port, print our current port source.
					if lastPrinted != "None":
						tee()
					tee("%c -> %c: " % (p, outp), "")
					lastPrinted = p
					bytesOnLine = 0
				else:
					if len(matched[p]["end"]) > 0:
						# The previous byte we looked at matched an end-of-message delim, go to new line.
						tee()
						tee("        ", "")
						bytesOnLine = 0
				matched[p]["start"] = ""
				matched[p]["end"] = ""
				for b in data:
					# Check if each incoming byte makes a start-of-message delim match.
					matched[p]["start"] = checkMsg(p, "start", b)
					if len(matched[p]["start"]) > 0:
						# We did match a start-of-message delim. 
						if len(matched[p]["start"]) > 1:
							# It was a multi-byte start-of-message delim, so remove previous data bytes
							# that we had alrady printed.
							tee("\b" * 5 * (len(matched[p]["start"]) - 1), "")
						if bytesOnLine >= len(matched[p]["start"]):
							# Need to erase and go to a new line now (also indent!)
							tee(" " * 5 * (len(matched[p]["start"]) - 1), "")
							tee()
							tee("        ", "")
						tee(" ".join(format("0x%02x" % int(n, 16)) for n in matched[p]["start"]) + " ", "")
						bytesOnLine = len(matched[p]["start"])
					else:
						# Data byte wasn't a start-of-message delim match, check if end-of-message delim..
						matched[p]["end"] = checkMsg(p, "end")
						tee("0x%02x " % b, "")
						bytesOnLine += 1
				# Send byte along to the other port now...
				port[outp].write(data)

	# Sniffing stopped, close ports and capture file, if applicable.
	for p in ["A", "B"]:
		port[p].close()
	if captureFile:
		captureFile.close()
		captureFile = None
		captureFileSize = 0
	print("\nCapture stopped\n\n")

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
	portA, portB = portSetApply()
	if not portA:
		return

	# Replay user-specfied traffic
	lineNum = 1
	direction = "unknown"
	for line in replayFileContents:
		startIndex = 0
		if line.find("A -> B") == 0 or line.find("B -> A") == 0:
			startIndex = line.find(":") + 1
			direction = line[0:startIndex - 1]
		if lineNum in lines:
			if direction == "unknown":
				print("Could not detect the direction to send replay data, skipping line %d..." % (lineNum))
			else:
				lineData = list(map(lambda b: int(b, 16), line[startIndex:].rstrip().split()))
				print("%s: %s" % (direction, line[startIndex:].rstrip()))
				if direction == "A -> B":
					portB.write(lineData)
				else:
					portA.write(lineData)
		lineNum += 1

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
            portset B /dev/ttyUSB0 115200
		'''
		portSet(arg.split())

	def do_msgget(self, arg):
		'''
Description: dump current message start/end delimiter settings

Usage: msgget
		'''
		msgGet(arg.split())

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

	def do_version(self, arg):
		print("v%s" % (version))

	def do_exit(self, arg):
		quit()

	def do_quit(self, arg):
		quit()

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
