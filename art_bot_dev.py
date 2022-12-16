#!/usr/bin/python3

# Script to start the developer interface for art-bot

from artbotlib.slack_output import SlackDeveloperOutput

regex_mapping = __import__("artbotlib.regex_mapping")

if __name__ == "__main__":
    so = SlackDeveloperOutput()
    print("---\nWelcome to the developer interface for Art-Bot.")
    print("To exit, type in 'exit' or use Ctrl-C\n---\n")
    try:
        while True:
            command = input("Enter your command: ")
            if command.lower() == "exit":
                break
            regex_mapping(so, command, None)
    except KeyboardInterrupt:
        print("Exiting...")
