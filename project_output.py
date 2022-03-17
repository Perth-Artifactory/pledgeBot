#!/usr/bin/python3

import json
import string
import random
from pprint import pprint

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# load Config
with open("config.json","r") as f:
    config = json.load(f)

########################
# Processing functions #
########################

# Load projects
def loadProjects():
    with open("projects.json","r") as f:
        return json.load(f)

users = {}
def lookup(id):
    if id not in users.keys():
        r = app.client.users_info(user=id)
        users[id] = (r["user"]["real_name"],r["user"]["name"])
    return users[id]

# Initialise slack

app = App(token=config["SLACK_BOT_TOKEN"])

projects = loadProjects()

for project in projects:
    p = projects[project]
    print("{} - created by {} (@{})".format(p["title"],lookup(p["created by"])[0],lookup(p["created by"])[1]))
    for pledge in p["pledges"]:
        print("${} - from {} (@{})".format(p["pledges"][pledge],lookup(pledge)[0],lookup(pledge)[1]))
    print("\n")
