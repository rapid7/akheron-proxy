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
def listSerialPorts(args = []):
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
def startSniff(args = ''):
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
		dataA = portA.read(10)
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
					tee('        ' + " ".join(matched["A"]["start"]) + " ", '')
				else:
					# Data byte wasn't a start-of-message delim match, check if end-of-message delim..
					matched["A"]["end"] = checkMsg("A", "end")
					tee('0x%02x ' % b, '')
			# Send byte along to port B.
			portB.write(dataA)

		# Process incoming data from port 'B'...
		dataB = portB.read(10)
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
					tee('        ' + " ".join(matched["B"]["start"]) + " ", '')
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

def promptHelpDisplay(command, data):
	print('%-8s: %s' % (command, data['desc']))
	if 'usage' in data:
		print('%+15s: %s' % ('usage', data['usage']))
	if 'examples' in data:
		for ex in data['examples']:
			print('%+15s: %s' % ('ex', ex))

# Display all available commands and descriptions at the interactive prompt.
def promptHelp(args = []):
	if len(args) == 1:
		if args[0] in gReplCmds:
			promptHelpDisplay(args[0], gReplCmds[args[0]])
		else:
			print('Unknown command \'%s\', type \'help\' for a list of valid commands.' %
				(args[0]))
	else:
		for k,v in sorted(gReplCmds.items()):
			if type(v) is dict:
				promptHelpDisplay(k, v)

# Global dict of commands and associated info supported in the interactive prompt.
gReplCmds = {
	'help': {
			'desc': 	'display available commands and descriptions',
			'method': 	promptHelp},
	'h': 'help',
	'quit': {
			'desc': 	'quit uart-proxy',
			'method': 	quit},
	'q': 'quit',
	'exit': 'quit',
	'list': {
			'desc':		'list all serial ports available to use',
			'usage':	'list [-v]',
			'method': 	listSerialPorts},
	'portget': {
			'desc':		'dump curreent UART port settings',
			'usage':	'portget',
			'examples':	[
						'portget'
					],
			'method': 	portGet},
	'portset': {
			'desc':		'apply UART port settings',
			'usage':	'portset <A|B> <device> <baud>',
			'examples':	[
						'portset A /dev/ttyUSB0 115200',
						'portset B /dev/ttyUSB0 115200'
					],
			'method': 	portSet},
	'msgset': {
			'desc':		'apply message parsing settings',
			'usage':	'msgset <start|end> <hex byte pattern>[,<hex byte pattern>,...]',
			'examples':	[
						'msgset start 0x01 0x00, 0x01 0x04, 0x07',
						'msgset end 0x99'
					],
			'method': 	msgSet},
	'start': {
			'desc': 	'start sniffing UART traffic',
			'usage':	'start [output file]',
			'examples':	[
						'start',
						'start captured.out'
					],
			'method': 	startSniff},
}

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
	while True:
		promptInput = input('> ')
		promptList = promptInput.split(' ')
		promptCmd = promptList[0].lower()
		# Lookup command.
		if promptCmd in gReplCmds:
			promptCmdVal = gReplCmds[promptCmd]
			if type(promptCmdVal) is str:
				# This command is an alias for another, look that other one up.
				promptCmdVal = gReplCmds[promptCmdVal]
			if 'method' in promptCmdVal:
				# Call the method associated with the command.
				if len(promptList) > 1:
					promptCmdVal['method'](promptList[1:])
				else:
					promptCmdVal['method']()
			else:
				print('Welp, this command is TBD!  :)')
		elif len(promptCmd):
			print('Unknown command \'%s\', type \'help\' for a list of valid commands.' %
				(promptCmd))

if __name__ == "__main__":
	main()
