import os
from slackclient import SlackClient
import configargparse
import time
import requests
import re

"""
Based on: https://www.fullstackpython.com/blog/build-first-slack-bot-python.html
"""

CHARITYBASE_URL = 'https://charitybase.uk/api/v0.2.0/charities'

def test_for_regno(message):
    regno_regex = r'\b([1-9][0-9]{5,6}|SC[O0-9]{5})\b'
    return re.findall(regno_regex, message)

def get_charity(regno):
    params = {
        "charityNumber": regno.replace('SCO', 'SC0'),
        "subNumber": 0,
        "fields": "mainCharity,registration,beta,objects",
        "limit": 1,
    }
    r = requests.get(CHARITYBASE_URL, params=params)
    result = r.json()
    if len(result.get("charities",[]))>0:
        return result["charities"][0]

def charity_search(search, limit=10):
    params = {
        "registered": True,
        "search": search,
        "fields": "mainCharity,registration,beta,objects",
        "sort": "-mainCharity.income",
        "limit": limit
    }
    r = requests.get(CHARITYBASE_URL, params=params)
    result = r.json()
    if len(result.get("charities",[]))>0:
        return result["charities"]

def get_charity_website(charity):

    website = charity.get("mainCharity", {}).get("website")
    if not website or website=="":
        website = get_cc_page(charity.get("charityNumber"))

    if not website.startswith("http"):
        website = "http://" + website

    return website

def get_cc_page(regno):
    return 'http://beta.charitycommission.gov.uk/charity-details/?regid={regno}&subid=0'.format(regno=regno)

def format_charity_attachment(c):
    attachment = {
        "fallback": "{} [{}]".format(c["name"], c["charityNumber"]),
        "title": "{} [{}]".format(c["name"], c["charityNumber"]),
        "title_link": get_charity_website(c),
        "text": c.get("beta", {}).get("activities"),
        "fields": [
            {"title": "Registered", "value": c.get("registration", [{}])[0].get("regDate","")[0:4], "short": True },
            {"title": "Income", "value": "£{:,.0f}".format(c.get("mainCharity", {}).get("income")), "short": True },
        ]
    }
    if c.get("beta", {}).get("employees"):
        attachment["fields"].append({"title": "Employees", "value": "{:,.0f}".format(c.get("beta", {}).get("employees", 0)), "short": True })

    if c.get("mainCharity", {}).get("companyNumber", "")!="":
        attachment["fields"].append({"title": "Company Number", "value": c.get("mainCharity", {}).get("companyNumber"), "short": True })
    return attachment

def handle_command(command, channel, thread_ts):
    """
        Receives commands directed at the bot and determines if they
        are valid commands. If so, then acts on the commands. If not,
        returns back what it needs for clarification.
    """
    response = "Not sure what you mean."
    attachments = []

    if isinstance(command, str):
        command = command.split(None, 1)

    if len(command)==2:
        q = command[1]
        command = command[0].lower()

        regnos = test_for_regno(q)
        if len(regnos)==1 and command!="find":
            q = regnos[0]
            command = "find"

        if command=="find":
            charity = get_charity(q)
            if charity:
                response = ""
                attachments = [format_charity_attachment(charity)]
            else:
                response = "Nothing found for _{}_".format(q)

        if command=="search":
            charities = charity_search(q, limit=5)
            response = "Searched for `{}`.".format(q)
            if not charities or len(charities)==0:
                response += " No results found."
            else:
                response += " {} result{} found".format( len(charities), '' if len(charities)==1 else 's' )
                attachments = [format_charity_attachment(c) for c in charities]

    slack_client.api_call("chat.postMessage", channel=channel,
                          text=response, as_user=True, attachments=attachments,
                          thread_ts=thread_ts)


def parse_slack_output(slack_rtm_output):
    """
        The Slack Real Time Messaging API is an events firehose.
        this parsing function returns None unless a message is
        directed at the Bot, based on its ID.
    """
    output_list = slack_rtm_output
    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and output['user']!=BOT_ID:
                if AT_BOT in output['text']:
                    # return text after the @ mention, whitespace removed
                    text = output['text'].split(AT_BOT)[1].strip().lower()
                    if text.startswith(('search','find')):
                        return text, output['channel'], output['ts']
                    else:
                        return ["search", text], output['channel'], output['ts']

                if output['channel'].startswith('D'):
                    if output['text'].startswith(('search','find')):
                        return output['text'], output['channel'], None
                    else:
                        return ["search", output['text']], output['channel'], None

                if "charity" in output['text'] and "search" in output['text']:
                    return None, None, None

    return None, None, None

if __name__ == "__main__":

    p = configargparse.ArgParser(ignore_unknown_config_file_keys=True)
    p.add('-c', '--config', default="example.cfg", is_config_file=True, help='config file path')

    # Slack connection details
    p.add('--access-token', help='Slack authorisation: access token')
    p.add('--bot-access-token', help='Slack Bot User authorisation: access token')

    # Slack bot
    p.add('--bot-name', help='Name of the bot', default="reg_charity_bot")
    p.add('--bot-id', help='ID of the bot')

    # Websocket config
    p.add('--websocket-delay', help='delay between reading from firehose (in seconds)', default=1, type=int)

    # Actions
    p.add("--get-bot-id", action="store_true", help='Print the bot ID')
    p.add("--debug", action='store_true', help="Debug mode (doesn't actually tweet)")


    options = p.parse_args()

    slack_client = SlackClient( options.bot_access_token )

    # if we're getting the Bot ID
    if options.get_bot_id:
        api_call = slack_client.api_call("users.list")
        if api_call.get('ok'):
            # retrieve all users so we can find our bot
            users = api_call.get('members')
            for user in users:
                if 'name' in user and user.get('name') == options.bot_name:
                    print("Bot ID for '" + user['name'] + "' is " + user.get('id'))
        else:
            print("could not find bot user with the name {}".format(options.bot_name ) )
        quit()

    if not options.bot_id:
        raise ValueError("Bot ID not found")

    BOT_ID = options.bot_id
    AT_BOT = "<@{}>".format(BOT_ID)

    if slack_client.rtm_connect():
        print("{} connected and running!".format( options.bot_name ))
        while True:
            command, channel, thread_ts = parse_slack_output(slack_client.rtm_read())
            if command and channel:
                handle_command(command, channel, thread_ts)
            time.sleep( options.websocket_delay )
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
