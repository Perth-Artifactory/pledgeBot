#!/usr/bin/python3

# Slack does not seem to have full type annotations, relevant types are marked with # type: ignore

import json
from datetime import datetime, timedelta
from typing import Any

import requests
from slack_bolt import App
from slack_sdk.web.slack_response import SlackResponse

########################
# Processing functions #
########################


# Load projects
def loadProjects() -> dict[str, dict[str, Any]]:
    with open("projects.json", "r") as f:
        return json.load(f)


def lookup(id: str) -> tuple[str, str, int]:
    if id not in users.keys():
        r: SlackResponse = app.client.users_info(user=id)
        tidy: str = input(f'TidyHQ ID for {r["user"]["real_name"]}? ')
        users[id] = (str(r["user"]["real_name"]), str(r["user"]["name"]), int(tidy))
        with open("tidyslack.json", "w") as f:
            json.dump(users, f, indent=4, sort_keys=True)
    return users[id]


def send_invoices(p: dict[str, Any]) -> None:
    if p.get("dgr", False):
        title_prefix = "Gift/Donation for: "
        message_suffix: str = f'\nAs a reminder your donation to this project is <{config["tax_info"]}|tax deductible>.'
        admin_suffix: str = f'\nThese invoices have been marked as <{config["tax_info"]}|tax deductible>.'
        category: int = int(config["tidyhq_dgr_category"])
    else:
        title_prefix = "Project pledge: "
        message_suffix = ""
        admin_suffix = "\nThese invoices have **not** been marked as tax deductible."
        category: int = int(config["tidyhq_project_category"])

    admin_notifaction: str = f'Invoices for {p["title"]} have been created: '
    sent_total = 0

    for pledge in p["pledges"]:
        amount: int = p["pledges"][pledge]
        details: dict[str, Any] = {
                "access_token": str(config["tidyhq_token"]),
                "reference": str(p["title"]),
                "name": str(title_prefix + p["title"]),
                "amount": amount,
                "included_tax_total": amount,
                "pre_tax_amount": amount,
                "due_date": datetime.now() + timedelta(days=14),
                "category_id": category,
                "contact_id": int(users[pledge][2]),
                "metadata": "Automatically added via api",
            }
        invoice_response: requests.Response = requests.post(
            invoices_url,
            params=details,
        )

        invoice: dict[str,Any] = invoice_response.json()
        print(
            f'${invoice["amount"]} invoice created for {users[pledge][0]} (https://{domain}.tidyhq.com/finances/invoices/{invoice["id"]}))'
        )
        admin_notifaction += f'\n* ${invoice["amount"]} for <@{users[pledge][1]}> - <https://{domain}.tidyhq.com/finances/invoices/{invoice["id"]}|{invoice["id"]}>'
        sent_total += int(invoice["amount"])

        # Open a slack conversation with the donor and get the channel ID
        r: SlackResponse = app.client.conversations_open(users=pledge) # type: ignore
        channel_id = str(r["channel"]["id"]) # type: ignore

        # Send a message to the donor to let them know an invoice has been created
        app.client.chat_postMessage( # type: ignore
            channel=channel_id, # type: ignore
            text=f'The funding goal for {p["title"]} has been met. I\'ve created an invoice for ${amount} which you can find <https://{domain}.tidyhq.com/public/invoices/{invoice["id"]}|here>.{message_suffix}',
        )

        print(f"Invoice notification sent to {users[pledge][0]}")

    # Open a slack conversation with the project creator and get the channel ID
    r = app.client.conversations_open(users=p["created by"]) # type: ignore
    channel_id: str = r["channel"]["id"] # type: ignore

    # Send a message to the project creator to let them know the invoices have been created
    app.client.chat_postMessage( # type: ignore
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

    app.client.chat_postMessage(channel=str(config["admin_channel"]), text=admin_notifaction) # type: ignore

invoices_url = "https://api.tidyhq.com/v1/invoices/"

# load Config
with open("config.json", "r") as f:
    config: dict[str,str|int] = json.load(f)

# Initialise slack

app = App(token=str(config["SLACK_BOT_TOKEN"]))

# Populate users from file
try:
    with open("tidyslack.json", "r") as f:
        users: dict[str,tuple[str,str,int]] = json.load(f)
except FileNotFoundError:
    users = {}

print("Pulling TidyHQ contacts...")

contacts: list[dict[str,Any]] = requests.get(
    "https://api.tidyhq.com/v1/contacts/",
    params={"access_token": config["tidyhq_token"]},
).json()

print(f"Received {len(contacts)} contacts")

print("Pulling data for Slack users not already cached...")
for contact in contacts:
    for field in contact["custom_fields"]:
        if (
            field["id"] == config["tidyhq_slack_id_field"]
            and field["value"] not in users.keys()
        ):
            r: SlackResponse = app.client.users_info(user=field["value"])
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

projects: dict[str,dict[str,Any]] = loadProjects()

# Get org name for URLs
print("Pulling TidyHQ organisation prefix...")
domain: str = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": config["tidyhq_token"]},
).json()["domain_prefix"]

print(f"Domain is {domain}.tidyhq.com")

for project in projects:
    p: dict[str,Any] = projects[project]
    print(
        f'{p["title"]} - created by {lookup(p["created by"])[0]} (@{lookup(p["created by"])[1]})'
    )

    if "pledges" not in p.keys():
        print("No pledges yet, skipped")
        continue

    for pledge in p["pledges"]:
        print(
            f'${p["pledges"][pledge]} - from {lookup(pledge)[0]} (@{lookup(pledge)[1]})'
        )
    print("\n")
    i: str = input("Invoice? [y/N]")
    if i == "y":
        send_invoices(p)
