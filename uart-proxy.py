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

def welcomeBanner():
	print('''
##########################
Welcome to the UART Proxy!
##########################
	''')

def listSerialPorts():
	for p in comports():
		print(p)

def setPort(args = ''):
	if len(args) != 3:
		print('Incorrect number of args, type \'help\' for usage')
		return
	port = args[0]
	deviceName = args[1]
	baud = args[2]
	if port != 'A' and port != 'B':
		print('Invalid \'port\' value, type \'help\' for usage')
		return

def startSniff(args = ''):
	portA = serial.Serial('/dev/ttyUSB1', 115200, timeout=0);
	portB = serial.Serial('/dev/ttyUSB2', 115200, timeout=0);
	print('Sniffing between ports, press CTRL-C to stop...')
	lastPrinted = 'None'
	while True:
		dataA = portA.read(10)
		if len(dataA) > 0:
			if lastPrinted != 'A':
				print()
				print('A -> B: ', end = '')
				lastPrinted = 'A'
			for b in dataA:
				print('%02x ' % b, end = '', flush = True)
			portB.write(dataA)
		dataB = portB.read(10)
		if len(dataB) > 0:
			if lastPrinted != 'B':
				print()
				print('B -> A: ', end = '')
				lastPrinted = 'B'
			for b in dataB:
				print('%02x ' % b, end = '', flush = True)
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
def promptHelp(args = ''):
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
			'method': 	listSerialPorts},
	'set': {
			'desc':		'apply UART port settings',
			'usage':	'set <A|B> <device> <baud>',
			'examples':	[
						'set A /dev/ttyUSB0 115200',
						'set B /dev/ttyUSB0 115200'],
			'method': 	setPort},
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

	# Parse (and action on) the command line args...
	cmdlineArgs = argParser.parse_args()

	if cmdlineArgs.listPorts:
		listSerialPorts()
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
