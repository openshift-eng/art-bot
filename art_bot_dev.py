#!/usr/bin/env python
# Script to start the developer interface for art-bot

from artbotlib.regex_mapping import map_command_to_regex
from artbotlib.slack_output import SlackDeveloperOutput
from artbotlib.util import log_config

if __name__ == "__main__":
    log_config()
    so = SlackDeveloperOutput()
    print("---\nWelcome to the developer interface for Art-Bot.")
    print("To exit, type in 'exit' or use Ctrl-C\n---\n")
    try:
        while True:
            command = input("Enter your command: ")
            if command.lower() == "exit":
                break
            map_command_to_regex(so, command, None)
    except KeyboardInterrupt:
        print("Exiting...")
