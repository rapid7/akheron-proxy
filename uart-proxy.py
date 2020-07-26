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

### Globals ###

msgDelims = {}
msgDelims["start"] = []
msgDelims["end"] = []

checkMsgBuffers = {}
checkMsgBuffers["A"] = []
checkMsgBuffers["B"] = []
checkMsgBufferMax = 0

### Methods ###

def welcomeBanner():
	print('''
##########################
Welcome to the UART Proxy!
##########################
	''')

def listSerialPorts(args = []):
	# TODO: workaround until REPL supports arg parsing for commands
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

def msgSet(args = ''):
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

def checkMsg(port, byte):
	global checkMsgBufferMax

	matched = False
	if checkMsgBufferMax > 0:
		#print("PJB here 1, port = %s, bytes - 0x%02x" % (port,byte))
		if len(checkMsgBuffers[port]) == checkMsgBufferMax:
			checkMsgBuffers[port].pop(0)
		checkMsgBuffers[port].append(hex(byte))
		for i in msgDelims["start"] + msgDelims["end"]:
			cmpStartIndex = 0
			if len(checkMsgBuffers[port]) < len(i):
				# Not enough bytes in buffer to compare with delim pattern
				continue
			elif len(checkMsgBuffers[port]) > len(i):
				# Compare the correct length of the delim pattern to match on
				cmpStartIndex = len(checkMsgBuffers[port]) - len(i)
			# print("comparing i (%s) with %s" % (str(i), checkMsgBuffers[port][cmpStartIndex:]))
			if checkMsgBuffers[port][cmpStartIndex:] == i:
				checkMsgBuffers[port] = []
				matched = True
				break
	return matched

def startSniff(args = ''):
	global checkMsgBufferMax
	checkMsgBufferMax = 0
	#if len(msgDelims["start"]) > 0 or len(msgDelims["end"]) > 0:
		# Setup for message parsing based on delimiters.
	for i in msgDelims["start"] + msgDelims["end"]:
		if len(i) > checkMsgBufferMax:
			checkMsgBufferMax = len(i)

	portA = serial.Serial('/dev/ttyUSB1', 115200, timeout=0);
	portB = serial.Serial('/dev/ttyUSB2', 115200, timeout=0);
	print('Sniffing between ports, press CTRL-C to stop...')
	lastPrinted = 'None'
	matched = {}
	matched["A"] = False
	matched["B"] = False
	while True:
		dataA = portA.read(10)
		if len(dataA) > 0:
			if lastPrinted != 'A':
				print()
				print('A -> B: ', end = '')
				lastPrinted = 'A'
			else:
				if matched["A"]:
					print()
					print('        ', end = '')
			matched["A"] = False
			for b in dataA:
				print('0x%02x ' % b, end = '', flush = True)
				matched["A"] = checkMsg("A", b)
			portB.write(dataA)
		dataB = portB.read(10)
		if len(dataB) > 0:
			if lastPrinted != 'B':
				print()
				print('B -> A: ', end = '')
				lastPrinted = 'B'
			else:
				if matched["B"]:
					print()
					print('        ', end = '')
			matched["B"] = False
			for b in dataB:
				print('0x%02x ' % b, end = '', flush = True)
				matched["B"] = checkMsg("B", b)
			portA.write(dataB)
	portA.close()
	portB.close()

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
			'usage':	'start',
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

	# "interactive prompt" (a.k.a. REPL).
	while True:
		promptInput = input('> ')
		promptList = promptInput.split(' ')
		promptCmd = promptList[0]
		# Lookup command.
		if promptCmd in gReplCmds:
			promptCmdVal = gReplCmds[promptList[0]]
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
		else:
			print('Unknown command \'%s\', type \'help\' for a list of valid commands.' %
				(promptCmd))

if __name__ == "__main__":
	main()
