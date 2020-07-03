#!/usr/bin/env python3
#
# !!!POC!!!
#
# uart-proxy application for sniffing, replaying, and modifying
# UART data!
#
# Copyright 2020

import argparse

def welcomeBanner():
	print('''
##########################
Welcome to the UART Proxy!
##########################
	''')

# Display all available commands and descriptions at the interactive prompt.
def promptHelp():
	for k,v in gReplCmds.items():
		if type(v) is dict:
			print('%-7s : %s' % (k, v['desc']))

# Global dict of commands and associated info supported in the interactive prompt.
gReplCmds = {
	'help': {'desc': 'display available commands and descriptions', 'method': promptHelp},
	'h': 'help',
	'quit': {'desc': 'quit uart-proxy', 'method': quit},
	'q': 'quit',
	'exit': 'quit',
	'set': {'desc': 'apply UART port settings'},
	'start': {'desc': 'start sniffing UART traffic'}
}

############################
# main!
############################
def main():

	# Setup command line arg parsing.
	argParser = argparse.ArgumentParser(description = 'UART Proxy app')
	argParser.add_argument('-b', action = 'store_true', dest = 'background',
		help = 'background the app for use with web browser UI (TBD)')
	argParser.add_argument('-q', action = 'store_true', dest = 'quiet',
		help = 'skip the banner on startup')

	# Parse (and action on) the command line args...
	cmdlineArgs = argParser.parse_args()

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
				promptCmdVal['method']()
			else:
				print('Welp, TBD!  :)')
		else:
			print('Unknown command \'%s\', type \'help\' for a list of valid commands.' %
				(promptCmd))

if __name__ == "__main__":
	main()
