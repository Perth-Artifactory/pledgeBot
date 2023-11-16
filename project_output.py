#!/usr/bin/python3

import json
import string
import random
import requests
from pprint import pprint
from datetime import datetime, timedelta

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

invoices_url = "https://api.tidyhq.com/v1/invoices/"

# load Config
with open("config.json", "r") as f:
    config = json.load(f)

########################
# Processing functions #
########################


# Load projects
def loadProjects():
    with open("projects.json", "r") as f:
        return json.load(f)


with open("tidyslack.json", "r") as f:
    users = json.load(f)


def lookup(id):
    if id not in users.keys():
        r = app.client.users_info(user=id)
        tidy = input("TidyHQ ID for {}? ".format(r["user"]["real_name"]))
        users[id] = (r["user"]["real_name"], r["user"]["name"], tidy)
        with open("tidyslack.json", "w") as f:
            json.dump(users, f, indent=4, sort_keys=True)
    return users[id]


def send_invoices(p):
    if p.get("dgr", False):
        title_prefix = "Gift/Donation for: "
        category = config["tidyhq_dgr_category"]
    else:
        title_prefix = "Project pledge: "
        category = config["tidyhq_project_category"]
    for pledge in p["pledges"]:
        amount = p["pledges"][pledge]
        r = requests.post(
            invoices_url,
            params={
                "access_token": config["tidyhq_token"],
                "reference": p["title"],
                "name": title_prefix + p["title"],
                "amount": amount,
                "included_tax_total": amount,
                "pre_tax_amount": amount,
                "due_date": datetime.now() + timedelta(days=14),
                "category_id": category,
                "contact_id": users[pledge][2],
                "metadata": "Automatically added via api",
            },
        )
        print(r.content)


# Initialise slack

app = App(token=config["SLACK_BOT_TOKEN"])

projects = loadProjects()

for project in projects:
    p = projects[project]
    print(
        "{} - created by {} (@{})".format(
            p["title"], lookup(p["created by"])[0], lookup(p["created by"])[1]
        )
    )
    for pledge in p["pledges"]:
        print(
            "${} - from {} (@{})".format(
                p["pledges"][pledge], lookup(pledge)[0], lookup(pledge)[1]
            )
        )
    print("\n")
    i = input("Invoice? [y/N]")
    if i == "y":
        send_invoices(p)
