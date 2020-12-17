#!/usr/bin/env python3
#
# akheron - UART proxy tool for inter-chip analysis, capturing, replaying, and
# modifying UART data!
#
# Copyright 2020

import argparse
import cmd
import functools
import operator
import os.path
import threading
from enum import Enum, auto
from time import sleep

import serial
from serial.tools.list_ports import comports

import serial_processor

try:
    import readline
except ImportError:
    readline = None


class SupportedChecksums(Enum):
    Checksum8Xor = auto()
    Checksum8Modulo256 = auto()
    Checksum8Modulo256Plus1 = auto()
    Checksum82sComplement = auto()


# Globals #####
version = "0.1"
histfile = os.path.join(os.path.expanduser("~"), ".akheron_history")
histsize = 1000

# Port settings, as provided via the 'portset' command.
portSettings = {
    "A": {
        "dev": "",
        "baud": 0
    },
    "B": {
        "dev": "",
        "baud": 0
    }
}

# Delimiters for start-of-message and end-of-message, as provided via 'delimset' command.
msgDelims = {
    "start": [],
    "end": []
}
delimMatching = False

# Pattern replacement/substitution, as provided via the 'replaceset' command.
replacePatterns = {
    "A": {},
    "B": {}
}

# Pattern replacement/substitution checksum recalculation method, as provided via the 'checksumset' command.
replaceChecksums = {
    "A": None,
    "B": None
}

# Temp buffers for holding incoming (RX'd) data to check against msgDelims.
checkMsgBuffers = {
    "A": [],
    "B": []
}
checkMsgBufferMax = 0

# When capturing to an external file
captureFile = None
captureFileSize = 0
trafficPassing = False
watching = False

# Resource locks
writerLock = {
    "A": threading.Lock(),
    "B": threading.Lock()
}
teeLock = threading.Lock()


# Methods #####

# Banner displayed at startup.
# Returns: n/a
def welcome_banner():
    print(f'''
######################################################
Akheron Proxy, UART proxy tool for inter-chip analysis
{f"version {version}".center(54, " ")}
######################################################
''')


# 'list' command, displays available serial ports.
# args:
#   '-v': enable verbose listing of more details
# Returns: n/a
def list_serial_ports(args=""):
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
def port_get(args=""):
    for p in ["A", "B"]:
        print("Port \"%s\": " % p, end="")
        if portSettings[p]["dev"]:
            print("device \"%s\" at %i" % (portSettings[p]["dev"], portSettings[p]["baud"]), end="")
        print()


# 'portset' command, allows user to set serial port settings.
# args:
#   [0]: specifies port ("A" or "B") being set
#   [1]: specifies the serial device name  (e.g. "/dev/ttyUSB0")
#   [2]: specifies the baud speed (e.g. 115200)
# Returns: n/a
def port_set(args=""):
    if len(args) != 3:
        print("Incorrect number of args, type \"help\" for usage")
        return
    port = args[0]
    device_name = args[1]
    baud = args[2]
    if port != "A" and port != "B":
        print("Invalid \"port\" value, type \"help\" for usage")
        return

    if trafficPassing:
        print("Cannot change port settings while passing traffic, please \"stop\" first")
        return

    # Dumb 'validation' of device and baud values: just try opening it and error if it didn't work!
    try:
        port_try = serial.Serial(device_name, int(baud), timeout=0)
    except serial.SerialException as e:
        print("Could not open device \"%s\" at baud \"%s\": %s" % (device_name, baud, str(e)))
        return

    # If we got here, it worked, so save off the values...
    port_try.close()

    portSettings[port]["dev"] = device_name
    portSettings[port]["baud"] = int(baud)

    # Warn if we're setting the port to the same device as the other port, as that's likely not wanted...
    if port == "A":
        other_port = "B"
    else:
        other_port = "A"
    if portSettings[port]["dev"] == portSettings[other_port]["dev"]:
        print("WARNING: both port \"A\" and \"B\" are set to device %s, YOU PROBABLY DON'T WANT THIS." % (
            portSettings[port]["dev"]))


# 'delimget' command, allows user to dump current start-of-message and end-of-message delimiters.
# Returns: n/a
def delim_get(args=""):
    for d in ["start", "end"]:
        print("%5s delimiters: " % d, end="")
        if msgDelims[d]:
            for e in msgDelims[d]:
                print(" ".join(format("0x%02x" % int(n, 16)) for n in e) + ", ", end="")
            print("\b\b ", end="")
        print()


# 'delimset' command, allows user to set start-of-message and end-of-message delimiters.
# args:
#   [0]: specifies type of message delimiter ("start" or "end") being set
#   [1]: specifies the value(s) to be considered delimiters
#        - values separated by spaces are considered a sequence
#        - commas denote separate delimiters
# Returns: n/a
def delim_set(args=""):
    global msgDelims

    if len(args) < 1:
        print("Incorrect number of args, type \"help\" for usage")
        return

    if trafficPassing:
        print("Cannot change message delims while passing traffic, please \"stop\" first")
        return

    setting_type = args[0]
    values_str = " ".join(args[1:])
    values = values_str.split(",")
    if setting_type != "start" and setting_type != "end":
        print("Invalid \"start/end\" value, type \"help\" for usage")
        return
    msgDelims[setting_type] = []
    for i in values:
        delim = []
        for j in i.split(" "):
            if len(j) > 0:
                delim.append(hex(int(j, 16)))
        msgDelims[setting_type].append(delim)


# Apply serial port device settings before executing sniffing/replay operations.
# Returns: Serial objects for open ports "A" and "B"
def port_set_apply():
    port_settings_missing = []
    for p in ["A", "B"]:
        if not portSettings[p]["dev"]:
            port_settings_missing.append(p)
    if len(port_settings_missing) > 0:
        port_str = "\" and \"".join(port_settings_missing)
        print("Port \"%s\" missing settings, please use the \"portset\" command to set device and baud." % port_str)
        return False

    # Apply serial port settings and open ports.
    port = {}
    for p in ["A", "B"]:
        try:
            port[p] = serial.Serial(portSettings[p]["dev"], portSettings[p]["baud"], timeout=0)
        except serial.SerialException as e:
            print("Could not open device \"%s\": %s" % (portSettings[p]["dev"], str(e)))
            if p == "B":
                port["A"].close()
            return False
    # NOTE: close these and return boolean
    for p in ["A", "B"]:
        port[p].close()
    return True


# 'replaceget' command, allows user to dump current "substitute pattern-X-for-Y" values.
# Returns: n/a
def replace_get(args=""):
    for p in ["A", "B"]:
        print("Replace port %c pattern X -> pattern Y:" % p)
        for r in replacePatterns[p]:
            print("  %s -> %s" % (str(" ".join(format("0x%02x" % int(n, 16)) for n in r.split(" "))),
                    str(" ".join(format("0x%02x" % int(n, 16)) for n in replacePatterns[p][r]))))


# 'replaceset' command, allows user to set "substitute pattern-X-for-Y" values.
# args:
#   [0]: specifies the port's ("A" or "B") traffic to apply these pattern replacements on
#   [1]: specifies the patterns to be replaces/swapped/substituted
#        - values separated by spaces are considered a sequence
#        - "arrow" (i.e. "->") denotes pattern X (left-hand side) should be swapped for Y (RHS)
#        - commas denote separate "substitute pattern-X-for-Y" pairs
# Returns: n/a
def replace_set(args=""):
    global replacePatterns

    if len(args) < 1:
        print("Incorrect number of args, type \"help\" for usage")
        return
    port = args[0]
    values_str = " ".join(args[1:])
    values = values_str.split(",")
    if port != "A" and port != "B":
        print("Invalid \"port\" value, type \"help\" for usage")
        return
    replacePatterns[port] = {}
    for i in values:
        if len(i) == 0:
            continue
        lhs_rhs_list = i.split("->")
        if len(lhs_rhs_list) != 2:
            print("Invalid replace pattern provided, skipping \"%s\"" % i)
            continue
        if len(lhs_rhs_list[0]) == 0 or len(lhs_rhs_list[1]) == 0:
            print("Invalid replace pattern provided, skipping \"%s\"" % i)
            continue
        pattern = {}
        index = 0
        for p in ["LHS", "RHS"]:
            pattern[p] = []
            for k in lhs_rhs_list[index].split(" "):
                if len(k) > 0:
                    pattern[p].append(hex(int(k, 16)))
            index += 1
        replacePatterns[port][" ".join(pattern["LHS"])] = pattern["RHS"]


# 'checksumget' command, allows user to output the current checksum recalculation used after pattern replacements
# Returns: n/a
def checksum_get(args=""):
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
def checksum_set(args=""):
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


def replace_patterns_if_matched(data, patterns, checksum_method):
    if len(patterns) == 0:
        # No patterns to match on, we're done
        return data
    for k, v in patterns.items():
        k_list = k.split(" ")
        match_list = [int(i, 16) for i in k_list]
        len_ml = len(match_list)
        for i in range(len(data) - len_ml + 1):
            if match_list == data[i:i + len_ml]:
                data[i:i + len_ml] = [int(val, 16) for val in v]
                checksum = calculate_checksum(data[:-1], checksum_method)
                if checksum is not None:
                    data[-1] = checksum
                break
    return data


def calculate_checksum(data, checksum_method):
    if checksum_method is None:
        # No checksum specified
        return None

    value = 0
    if checksum_method == SupportedChecksums.Checksum8Xor:
        value = functools.reduce(operator.xor, data)
    elif checksum_method == SupportedChecksums.Checksum8Modulo256:
        value = sum(data) % 256
    elif checksum_method == SupportedChecksums.Checksum8Modulo256Plus1:
        value = (sum(data) % 256) + 1
    elif checksum_method == SupportedChecksums.Checksum82sComplement:
        value = -(sum(data) % 256) & 0xFF

    return value


# Check a received set of bytes for a match to a start-of-message or end-of-message delim.
# port: indicates which port ("A" or "B") delimiters should be used for this check
# startOrEnd: indicates if the "start" or "end" message delimiters should be checked.
# byte: new byte of data received
# Returns: matched string (delim) value OR an empty string if no match
def check_msg(port, start_or_end, byte=None):
    global checkMsgBufferMax

    matched_str = ""
    if checkMsgBufferMax > 0:
        if byte:
            if len(checkMsgBuffers[port]) == checkMsgBufferMax:
                # Our message buffer is full, remove the oldest char.
                checkMsgBuffers[port].pop(0)
            checkMsgBuffers[port].append(hex(byte))
        for i in msgDelims[start_or_end]:
            cmp_start_index = 0
            if len(checkMsgBuffers[port]) < len(i):
                # Not enough bytes in buffer to compare with delim pattern
                continue
            elif len(checkMsgBuffers[port]) > len(i):
                # Compare the correct length of the delim pattern to match on
                cmp_start_index = len(checkMsgBuffers[port]) - len(i)
            if checkMsgBuffers[port][cmp_start_index:] == i:
                # Matched a delimiter!
                checkMsgBuffers[port] = []
                matched_str = i
                break
    return matched_str


# Similar to the *nix command 'tee', this method sends output to both the display
#   and capture file, if in use.
# string: string value to display+write
# end: trailing character for 'string'
# Returns: n/a
def tee(string="", end="\n"):
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
            print(string, end=end, flush=True)


# Capturing traffic between two ports.
# args:
#   [0]: filename to write captured data to
# Returns: n/a
def capture_traffic_start(args=""):
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
    capture_file_name = args[0]
    try:
        captureFile = open(capture_file_name, "w")
    except IOError as e:
        print("File \"%s\" could not be opened: %s" % (capture_file_name, str(e)))
        return

    print("Saving captured traffic to \"%s\"..." % capture_file_name)


# Capturing traffic between two ports.
# args:
#   [0]: filename to write captured data to
# Returns: n/a
def capture_traffic_stop(args=""):
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
def dump_capture(args=""):
    if len(args) != 1:
        print("Incorrect number of args, type \"help\" for usage")
        return
    dump_file_name = args[0]

    try:
        dump_file = open(dump_file_name, "r")
    except IOError as e:
        print("File \"%s\" could not be opened: %s" % (dump_file_name, str(e)))
        return
    dump_file_contents = dump_file.readlines()

    line_num = 1
    for line in dump_file_contents:
        print("%5u: %s" % (line_num, line.rstrip()))
        line_num += 1


# Replaying traffic between two ports.
# args:
#   [0]: filename to replay captured data from
#   [1]: line(s) of the replay file of the data to be replayed, commas and hyphens supported (OPTIONAL)
# Returns: n/a
def replay_traffic(args=""):
    if len(args) == 0 or len(args) > 2:
        print("Incorrect number of args, type \"help\" for usage")
        return

    if not trafficPassing:
        print("Cannot replay traffic while traffic is blocked, please \"start\" first")
        return

    replay_file_name = args[0]
    try:
        replay_file = open(replay_file_name, "r")
    except IOError as e:
        print("File \"%s\" could not be opened: %s" % (replay_file_name, str(e)))
        return
    replay_file_contents = replay_file.readlines()

    lines = []
    if len(args) == 2:
        values_str = " ".join(args[1:])
        values = values_str.split(",")
        for i in values:
            hyphen_pos = i.find("-")
            if hyphen_pos > 0:
                range_start = int(i[0:hyphen_pos])
                range_end = int(i[hyphen_pos + 1:]) + 1
                lines.extend(list(range(range_start, range_end)))
            else:
                lines.append(int(i))
    else:
        lines = list(range(1, len(replay_file_contents) + 1))

    # Apply serial port settings
    if not port_set_apply():
        # Port settings not valid...
        return

    # Replay user-specified traffic
    line_num = 1
    direction = "unknown"
    # Make an initial pass to determine which direction we'll limit replay to...
    for line in replay_file_contents:
        if line.find("A -> B") == 0 or line.find("B -> A") == 0:
            direction = line[0:line.find(":")]
        if line_num in lines and direction != "unknown":
            break
        line_num += 1
    if direction == "unknown":
        print(
            "Could not detect the direction to send replay data, make sure your capture file and line selection are valid")
        return

    if direction == "A -> B":
        p = "A"
        outp = "B"
        out_dev_id = serial_processor.DeviceIdentifier.BETA
    else:
        p = "B"
        outp = "A"
        out_dev_id = serial_processor.DeviceIdentifier.ALPHA

    # Acquire lock for writing to the "output port"
    with writerLock[outp]:
        print("Replaying data from %s, press CTRL-C to exit watch mode..." % direction, end="")
        global watching
        watching = True
        curr_direction = "unknown"
        line_num = 1
        for line in replay_file_contents:
            start_index = 0
            if line.find("A -> B") == 0 or line.find("B -> A") == 0:
                start_index = line.find(":") + 1
                curr_direction = line[0:start_index - 1]
            if line_num in lines and curr_direction == direction:
                line_data = list(map(lambda b: int(b, 16), line[start_index:].rstrip().split()))
                line_data = replace_patterns_if_matched(line_data, replacePatterns[p], replaceChecksums[p])
                # print("%s: %s" % (direction, " ".join(format("0x%02x" % int(n)) for n in line_data) + " "))
                processor.write(out_dev_id, bytes(line_data))
                tee("\n%s: %s" % (direction, " ".join(format("0x%02x" % int(n)) for n in line_data) + " "), "")
            line_num += 1
        global lastPrinted
        lastPrinted = p
    watch_wait_exit()


def data_received_callback_a(data):
    # print("PJB: callbackA, data = %s, type %s" % (str(data), str(type(data))))
    data_received_callback(data, "A")
    return data


def data_received_callback_b(data):
    # print("PJB: callbackB, data = %s, type %s" % (str(data), str(type(data))))
    data_received_callback(list(data), "B")
    return data


lastPrinted = "None"
portDataOutBuffer = {}
delimMatched = {}
bytesOnLine = 0


def data_received_callback(data, p):
    # When matching on start/stop message delimiters, we'll buffer the data in case
    # there are replacements/substitutions to make...
    global delimMatched
    global lastPrinted
    global portDataOutBuffer
    global bytesOnLine

    # Alternate reading data from each port in the connection...
    if p == "A":
        outp = "B"
        out_dev_id = serial_processor.DeviceIdentifier.BETA
    else:
        outp = "A"
        out_dev_id = serial_processor.DeviceIdentifier.ALPHA

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
                delimMatched[p]["start"] = check_msg(p, "start", b)
                if len(delimMatched[p]["start"]) > 0:
                    portDataOutBuffer[outp].append(b)
                    # We did match a start-of-message delim.
                    if len(delimMatched[p]["start"]) > 1:
                        # It was a multi-byte start-of-message delim, so remove previous data bytes
                        # that we had already printed.
                        tee("\b" * 5 * (len(delimMatched[p]["start"]) - 1), "")
                    if bytesOnLine >= len(delimMatched[p]["start"]):
                        # Need to erase and go to a new line now (also indent!)
                        tee(" " * 5 * (len(delimMatched[p]["start"]) - 1), "")
                        tee()
                        tee("        ", "")
                    tee(" ".join(format("0x%02x" % int(n, 16)) for n in delimMatched[p]["start"]) + " ", "")
                    bytesOnLine = len(delimMatched[p]["start"])
                    # Send the buffered message out the correct port and reset the databuffer...
                    last_data_index = len(portDataOutBuffer[outp]) - len(delimMatched[p]["start"])
                    processor.write(out_dev_id, bytes(portDataOutBuffer[outp][:last_data_index]))
                    portDataOutBuffer[outp] = [int(n, 16) for n in delimMatched[p]["start"]]
                else:
                    # Data byte wasn't a start-of-message delim match, check if end-of-message delim...
                    delimMatched[p]["end"] = check_msg(p, "end")
                    tee("0x%02x " % b, "")
                    bytesOnLine += 1
                    if delimMatching:
                        portDataOutBuffer[outp].append(b)
                    if len(delimMatched[p]["end"]) > 0:
                        # Send the buffered message out the correct port and reset the databuffer...
                        processor.write(out_dev_id, bytes(portDataOutBuffer[outp]))
                        portDataOutBuffer[outp] = []
                if not delimMatching:
                    # Send byte along to the other port now...
                    processor.write(out_dev_id, b.to_bytes(1, byteorder='big'))


processor = None


# Start traffic between two ports.
# args: none
# Returns: n/a
def start_traffic(args=""):
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
    if not port_set_apply():
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
        'data_received_callback': data_received_callback_a
    }
    conf_b = {
        'device': portSettings["B"]["dev"],
        'baudrate': portSettings["B"]["baud"],
        'parity': serial.PARITY_NONE,
        'stopbits': serial.STOPBITS_ONE,
        'bytesize': serial.EIGHTBITS,
        'timeout': 1,
        'pass_through': False,
        'data_received_callback': data_received_callback_b
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
def stop_traffic(args=""):
    global trafficPassing
    trafficPassing = False

    if processor:
        processor.stop()
        print(
            "Data now BLOCKED between ports \"%s\" <-> \"%s\"." % (portSettings["A"]["dev"], portSettings["B"]["dev"]))
    return


def watch_wait_exit():
    while watching:
        sleep(.25)


def watch(args=""):
    if not trafficPassing:
        print("Data is not currently being passed between ports; run 'start' command first.")
        return

    global watching
    print("Watching data passed between ports. Press CTRL-C to stop...")
    watching = True


def shutdown():
    if processor:
        # Cleanup serial port threads...
        processor.stop()
    if captureFile:
        # Close our existing capture...
        captureFile.close()


# Implementation of our REPL functionality.
class ProxyRepl(cmd.Cmd):
    prompt = "> "
    use_rawinput = True

    def cmdloop_until_keyboard_interrupt(self):
        try:
            super().cmdloop()
        except KeyboardInterrupt:
            shutdown()
            self.__write_history()

    def onecmd(self, line):
        try:
            return super().onecmd(line)
        except KeyboardInterrupt:
            global watching
            if watching:
                # stop watching
                watching = False
                self.stdout.write("\nWatch mode exited.\n")
                # don't stop interpretation of commands by the interpreter
                return False
            else:
                shutdown()
                # stop interpretation of commands by the interpreter
                return True

    def preloop(self):
        if readline and os.path.exists(histfile):
            readline.read_history_file(histfile)

    def postloop(self):
        self.__write_history()

    @staticmethod
    def __write_history():
        if readline:
            readline.set_history_length(histsize)
            readline.write_history_file(histfile)

    def do_list(self, arg):
        """
Description: list all serial ports available to use

Usage: list [-v]
        """
        list_serial_ports(arg.split())

    def do_portget(self, arg):
        """
Description: dump current UART port settings

Usage: portget
        """
        port_get(arg.split())

    def do_portset(self, arg):
        """
Description: apply UART port settings

Usage: portset <A|B> <device> <baud>

Example(s): portset A /dev/ttyUSB0 115200
            portset B /dev/ttyUSB1 115200
        """
        port_set(arg.split())

    def do_delimget(self, arg):
        """
Description: dump current message start/end delimiter settings

Usage: delimget
        """
        delim_get(arg.split())

    def do_delimset(self, arg):
        """
Description: apply message parsing settings

Usage:	delimset <start|end> <hex byte pattern>[,<hex byte pattern>,...]

Example(s): delimset start 0x01 0x00, 0x01 0x04, 0x07
            delimset end 0x99
        """
        delim_set(arg.split())

    def do_replaceget(self, arg):
        """
Description: dump current message pattern replace/substitute settings

Usage: replaceget
        """
        replace_get(arg.split())

    def do_replaceset(self, arg):
        """
Description: apply message pattern replace/substitute settings

Usage:	replaceset <A|B> <hex byte pattern to match on> -> <hex byte pattern to replace with>[,<hex byte pattern to match on>,...]

Example(s): replaceset A 0x31 -> 0x32
            replaceset A 0x31 0x32 0x33 -> 0x21 0x22 0x23, 0x45 0x46 -> 0x55
        """
        replace_set(arg.split())

    def do_checksumget(self, arg):
        """
Description: output the current checksum recalculation used after message pattern replacement

Usage: checksumget
        """
        checksum_get(arg.split())

    def do_checksumset(self, arg):
        """
Description: set checksum recalculation used after message pattern replacement.
Note: This should be used with start delim patterns since the computed
checksum will be placed at the end of the message.

Usage:	checksumset <A|B> <checksum number or name>

Example(s): checksumset A 1
            checksumset B Checksum8Modulo256
        """
        checksum_set(arg.split())

    def help_checksumset(self):
        arg = "checksumset"
        try:
            doc = getattr(self, "do_" + arg).__doc__
            if doc:
                self.stdout.write("%s\n" % str(doc))
                self.stdout.write("Available Checksums:\n")
                for checksum in SupportedChecksums:
                    self.stdout.write(f"  {checksum.value}: {checksum.name}\n")
                self.stdout.write("\n")
                return
        except AttributeError:
            pass
        self.stdout.write("%s\n" % str(self.nohelp % (arg,)))
        return

    def do_capturestart(self, arg):
        """
Description: start capturing UART traffic

Usage:	capturestart <output capture file>

Example(s): capturestart
            capturestart sniffed.out
        """
        capture_traffic_start(arg.split())

    def do_capturestop(self, arg):
        """
Description: stop capturing UART traffic

Usage:	capturestop

Example(s): capturestop
            capturestop sniffed.out
        """
        capture_traffic_stop(arg.split())

    def do_capturedump(self, arg):
        """
Description: dump capture file contents

Usage: capturedump <capture file>

Example(s): capturedump sniffed.out
        """
        dump_capture(arg.split())

    def do_replay(self, arg):
        """
Description: start replaying-and-forwarding UART traffic

Usage: replay <capture file> [line number(s) to replay]

Example(s): replay sniffed.out
            replay sniffed.out 1,4
            replay sniffed.out 2-10
        """
        replay_traffic(arg.split())

    def do_start(self, arg):
        """
Description: start forwarding UART traffic

Usage:	start

Example(s): start
        """
        start_traffic(arg.split())

    def do_stop(self, arg):
        """
Description: stop forwarding UART traffic

Usage:	stop

Example(s): stop
        """
        stop_traffic(arg.split())

    def do_watch(self, arg):
        """
Description: watch UART traffic

Usage:	watch
        """
        watch(arg.split())
        watch_wait_exit()

    def do_version(self, arg):
        print("v%s" % version)

    def do_exit(self, arg):
        shutdown()
        return True

    def do_quit(self, arg):
        shutdown()
        return True

    def emptyline(self):
        pass


############################
# main!
############################
def main():
    # Setup command line arg parsing.
    arg_parser = argparse.ArgumentParser(description="UART proxy tool")
    arg_parser.add_argument("-l", action="store_true", dest="listPorts",
                            help="list all serial ports available to use")
    arg_parser.add_argument("-b", action="store_true", dest="background",
                            help="background the app for use with web browser UI (TBD)")
    arg_parser.add_argument("-q", action="store_true", dest="quiet",
                            help="skip the banner on startup")
    arg_parser.add_argument("-V", "--version", action="store_true", dest="version",
                            help="show version information")
    arg_parser.add_argument("-v", "--verbose", action="store_true",
                            help="show more information")

    # Parse (and action on) the command line args...
    cmdline_args = arg_parser.parse_args()

    if cmdline_args.listPorts:
        args = []
        if cmdline_args.verbose:
            args.append("-v")
        list_serial_ports(args)
        return

    if cmdline_args.version:
        print("v%s" % version)
        return

    if cmdline_args.background:
        print("Background logic is TBD, running in interactive mode...")

    if not cmdline_args.quiet:
        welcome_banner()

    # "interactive prompt" (a.k.a. REPL).
    ProxyRepl().cmdloop_until_keyboard_interrupt()


if __name__ == "__main__":
    main()
