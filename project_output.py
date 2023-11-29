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
        message_suffix = (
            f'\nAs a reminder your donation to this project is <{config["tax_info"]}|tax deductible>.'
        )
        admin_suffix = f'\nThese invoices have been marked as <{config["tax_info"]}|tax deductible>.'
        category = config["tidyhq_dgr_category"]
    else:
        title_prefix = "Project pledge: "
        message_suffix = ""
        admin_suffix = "\nThese invoices have **not** been marked as tax deductible."
        category = config["tidyhq_project_category"]

    admin_notifaction = f'Invoices for {p["title"]} have been created: '
    sent_total = 0

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
        invoice = r.json()
        print(
            f'${invoice["amount"]} invoice created for {users[pledge][0]} (https://{domain}.tidyhq.com/finances/invoices/{invoice["id"]}))'
        )
        admin_notifaction += f'\n* ${invoice["amount"]} for <@{users[pledge][1]}> - <https://{domain}.tidyhq.com/finances/invoices/{invoice["id"]}|{invoice["id"]}>'
        sent_total += invoice["amount"]

        # Open a slack conversation with the donor and get the channel ID
        r = app.client.conversations_open(users=pledge)
        channel_id = r["channel"]["id"]

        # Send a message to the donor to let them know an invoice has been created
        app.client.chat_postMessage(
            channel=channel_id,
            text=f'The funding goal for {p["title"]} has been met. I\'ve created an invoice for ${amount} which you can find <https://{domain}.tidyhq.com/public/invoices/{invoice["id"]}|here>.{message_suffix}',
        )

        print(f"Invoice notification sent to {users[pledge][0]}")

    # Open a slack conversation with the project creator and get the channel ID
    r = app.client.conversations_open(users=p["created by"])
    channel_id = r["channel"]["id"]

    # Send a message to the project creator to let them know the invoices have been created
    app.client.chat_postMessage(
        channel=channel_id,
        text=f'The funding goal for a project you created ({p["title"]}) has been met and invoices have been sent out. Please contact the Treasurer for the next steps.',
    )

    print(
        f'Invoice notification sent to {users[p["created by"]][0]} as project creator'
    )

    # Send invoice creation details to the admin channel

    admin_notifaction += f'\n\nProject goal: ${p["total"]}'
    admin_notifaction += f"\nTotal sent: ${sent_total}"
    admin_notifaction += admin_suffix
    admin_notifaction += f'\n\nA notification has also been sent to <@{p["created by"]}> as the project creator. They\'ve been asked to contact the Treasurer for the next steps.'

    app.client.chat_postMessage(channel=config["admin_channel"], text=admin_notifaction)


# Initialise slack

app = App(token=config["SLACK_BOT_TOKEN"])

# Populate users from file
try:
    with open("tidyslack.json", "r") as f:
        users = json.load(f)
except FileNotFoundError:
    users = {}

print("Pulling TidyHQ contacts...")

r = requests.get(
    "https://api.tidyhq.com/v1/contacts/",
    params={"access_token": config["tidyhq_token"]},
)

print("Received {} contacts".format(len(r.json())))

print("Pulling data for Slack users not already cached...")
for contact in r.json():
    for field in contact["custom_fields"]:
        if (
            field["id"] == config["tidyhq_slack_id_field"]
            and field["value"] not in users.keys()
        ):
            r = app.client.users_info(user=field["value"])
            users[field["value"]] = (
                r["user"].get(
                    "real_name", r["user"].get("display_name", r["user"]["name"])
                ),
                r["user"]["name"],
                contact["contact_id"],
            )
            print(f'Added {r["user"]["name"]} to ({contact["contact_id"]})')

with open("tidyslack.json", "w") as f:
    json.dump(users, f, indent=4, sort_keys=True)

projects = loadProjects()

# Get org name for URLs
print("Pulling TidyHQ organisation prefix...")
r = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": config["tidyhq_token"]},
)
domain = r.json()["domain_prefix"]
print(f"Domain is {domain}.tidyhq.com")

for project in projects:
    p = projects[project]
    print(
        "{} - created by {} (@{})".format(
            p["title"], lookup(p["created by"])[0], lookup(p["created by"])[1]
        )
    )

    if "pledges" not in p.keys():
        print("No pledges yet, skipped")
        continue

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
