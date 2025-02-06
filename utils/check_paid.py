import json
import requests
from pprint import pprint
from datetime import datetime
from slack_bolt import App
import sys


def check_paid(project):
    # Get the expected invoice category and name based on dgr status
    if project.get("dgr", False):
        invoice_name = f"Gift/Donation for: {project['title']}"
    else:
        invoice_name = f"Project pledge: {project['title']}"

    # reverse the list so that the most recent invoices are first

    relevant_invoices = []
    for invoice in all_invoices:
        if invoice.get("name", False) == invoice_name:
            relevant_invoices.append(invoice)

    # If there are no invoices, raise an error
    if not relevant_invoices:
        raise Exception(f"No invoices found for project {project['title']}")

    # If there are invoices, check if they are paid
    paid_invoices = []
    paid_total = 0
    unpaid_invoices = []
    unpaid_total = 0

    for invoice in relevant_invoices:
        if invoice["paid"]:
            paid_invoices.append(invoice)
            paid_total += invoice["amount"]
        else:
            unpaid_invoices.append(invoice)
            unpaid_total += invoice["amount_due"]

    print(f"Project: {project['title']}")
    print(f"Paid invoices: {len(paid_invoices)} ${paid_total}/${project['total']}")
    print(
        f"Unpaid invoices: {len(unpaid_invoices)} ${unpaid_total}/${project['total']}"
    )

    if paid_total >= project["total"]:
        print("Project is fully paid")
        return {
            "paid": True,
            "paid_total": paid_total,
            "unpaid_total": unpaid_total,
            "paid_invoices": paid_invoices,
            "unpaid_invoices": unpaid_invoices,
        }
    else:
        print("Project is not fully paid")
        return {
            "paid": False,
            "paid_total": paid_total,
            "unpaid_total": unpaid_total,
            "paid_invoices": paid_invoices,
            "unpaid_invoices": unpaid_invoices,
        }


# Get command line arguments
include_unpaid = False
if "--include-unpaid" in sys.argv:
    include_unpaid = True

# load config file
with open("config.json", "r") as f:
    config = json.load(f)

# Load projects file
with open("projects.json", "r") as f:
    projects = json.load(f)

# Initialise slack client for sending messages
global invoice_slack_app
invoice_slack_app = App(token=str(config["SLACK_BOT_TOKEN"]))

# Get all recent invoices from TidyHQ

r = requests.get(
    "https://api.tidyhq.com/v1/invoices",
    params={"access_token": str(config["tidyhq_token"])},
)
all_invoices = r.json()[::-1]

# Get a list of TidyHQ contacts
r = requests.get(
    "https://api.tidyhq.com/v1/contacts",
    params={"access_token": str(config["tidyhq_token"])},
)

contacts_raw = r.json()
# contacts come as a list of dicts, convert to a dict of dicts
contacts = {contact["id"]: contact for contact in contacts_raw}

# Get domain to construct links
r = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": str(config["tidyhq_token"])},
)

invoice_url_template = (
    f"https://{r.json()['domain_prefix']}.tidyhq.com/finances/invoices/{{}}"
)
contact_url_template = f"https://{r.json()['domain_prefix']}.tidyhq.com/contacts/{{}}"

# Iterate over projects and look for ones that have a funding timestamp but not a reconciliation timestamp
projects_to_check = []

for project_id in projects:
    project = projects[project_id]
    if project.get("funded at", False) and not project.get("reconciled at", False):
        projects_to_check.append(project_id)

# Iterate over projects to check and check if they have been paid
for project_id in projects_to_check:
    project = projects[project_id]
    info = check_paid(project)
    if info.get("paid", True) or include_unpaid:
        # If the project is fully paid, update the projects.json file
        if info.get("paid", True):
            project["reconciled at"] = int(datetime.now().timestamp())
            with open("projects.json", "w") as f:
                json.dump(projects, f, indent=4, sort_keys=True)
            print(f"Updated {project['title']} in projects.json")
            admin_message = (
                f"Project `{project['title']}` has been fully paid and reconciled"
            )
        else:
            admin_message = f"Project `{project['title']}` has outstanding invoices"

        # Send a message to slack
        r = invoice_slack_app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=admin_message,
        )

        # Reply to the thread with more details
        invoice_slack_app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=f"{len(info['paid_invoices'])} Paid invoices: ${info['paid_total']} / ${project['total']}",
            thread_ts=r["ts"],
        )

        # Format a list of paid invoices
        invoice_str = ""

        for invoice in info["paid_invoices"]:
            invoice_str += f"• <{contact_url_template.format(invoice['contact_id'])}|{contacts[invoice['contact_id']]['display_name']}> - <{invoice_url_template.format(invoice['id'])}|${invoice['amount']}>\n"

        invoice_slack_app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=invoice_str,
            thread_ts=r["ts"],
        )

        if include_unpaid and not info["paid"]:
            invoice_str = ""
            for invoice in info["unpaid_invoices"]:
                invoice_str += f"• <{contact_url_template.format(invoice['contact_id'])}|{contacts[invoice['contact_id']]['display_name']}> - <{invoice_url_template.format(invoice['id'])}|${invoice['amount_due']}>\n"

            invoice_slack_app.client.chat_postMessage(
                channel=config["admin_channel"],
                text=f"{len(info['unpaid_invoices'])} Unpaid invoices: ${info['unpaid_total']} / ${project['total']}",
                thread_ts=r["ts"],
            )

            invoice_slack_app.client.chat_postMessage(
                channel=config["admin_channel"],
                text=invoice_str,
                thread_ts=r["ts"],
            )
