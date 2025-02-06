#!/usr/bin/python3

import json
import random
import string
import time
from datetime import datetime
from pprint import pprint  # type: ignore # This has been left in for debugging purposes
from typing import Any
import utils.project_output

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.web.client import WebClient  # for typing
from slack_sdk.web.slack_response import SlackResponse  # for typing

# load Config
with open("config.json", "r") as f:
    config = json.load(f)

########################
# Processing functions #
########################


# Load projects
def load_projects():
    with open("projects.json", "r") as f:
        return json.load(f)


# Update project, data should be an entire project initially pulled with get_project
def write_project(id: str, data: dict[str, Any], user: str | bool):
    projects = load_projects()
    if id not in projects.keys():
        data["created by"] = user
        data["created at"] = int(time.time())
        data["last updated by"] = user
        data["last updated at"] = int(time.time())
        # Projects should default to DGR False
        data["dgr"] = False
        projects[id] = data
        with open("projects.json", "w") as f:
            json.dump(projects, f, indent=4, sort_keys=True)

        # Notify the admin channel
        app.client.chat_postMessage(  # type: ignore
            channel=config["admin_channel"],
            text=f'"{data["title"]}" has been created by <@{user}>. It will need to be approved before it will show up on the full list of projects or to be marked as DGR eligible. This can be completed by any member of <!subteam^{config["admin_group"]}> by clicking on my name or waiting for the creator to request approval themselves.',
        )

    else:
        if user:
            data["last updated by"] = user
            data["last updated at"] = int(time.time())

            # Send a notice to the admin channel and add further details as a thread
            reply = app.client.chat_postMessage(  # type: ignore
                channel=config["admin_channel"],
                text=f'"{data["title"]}" has been updated by <@{user}>.',
            )

            app.client.chat_postMessage(  # type: ignore
                channel=config["admin_channel"],
                thread_ts=reply["ts"],  # type: ignore
                text=f"Old:\n```{json.dumps(load_projects()[id], indent=4, sort_keys=True)}```",
            )

            app.client.chat_postMessage(  # type: ignore
                channel=config["admin_channel"],
                thread_ts=reply["ts"],  # type: ignore
                text=f"New:\n```{json.dumps(data, indent=4, sort_keys=True)}```",
            )

            # Send a notice to the project creator if they're not the one updating it
            if data["created by"] != user:
                # Open a slack conversation with the creator and get the channel ID
                r: SlackResponse = app.client.conversations_open(users=data["created by"])  # type: ignore
                channel_id: str = str(r["channel"]["id"])  # type: ignore

                # Notify the creator
                app.client.chat_postMessage(  # type: ignore
                    channel=channel_id,
                    text=f'A project you created ({data["title"]}) has been updated by <@{user}>.',
                )

        projects[id] = data
        with open("projects.json", "w") as f:
            json.dump(projects, f, indent=4, sort_keys=True)


def get_project(id: str) -> dict[str, Any]:
    projects = load_projects()
    if id in projects.keys():
        return projects[id]
    else:
        return {
            "title": "Your new project",
            "desc": "",
            "img": None,
            "total": 0,
            "approved": False,
        }


def unapprove_project(id: str) -> None:
    project = get_project(id)
    project["approved"] = False
    write_project(id, project, user=False)


def log_promotion(project_id: str, slack_response: SlackResponse) -> None:
    project = get_project(project_id)
    if "promotions" not in project.keys():
        project["promotions"] = []
    project["promotions"].append(  # type: ignore
        {"channel": slack_response["channel"], "ts": slack_response["ts"]}
    )
    write_project(project_id, project, user=False)


def delete_project(id: str) -> None:
    projects = load_projects()
    del projects[id]
    with open("projects.json", "w") as f:
        json.dump(projects, f, indent=4, sort_keys=True)


def validate_id(id: str) -> bool:
    allowed = set(string.ascii_letters + string.digits + "_" + "-")
    if set(id) <= allowed:
        return True
    return False


def pledge(
    id: str, amount: int | str, user: str, percentage: bool = False
) -> list[dict[str, Any]]:
    project: dict[str, Any] = load_projects()[id]
    if "pledges" not in project.keys():
        project["pledges"] = {}
    if amount == "remaining":
        current_total = 0
        for pledge in project["pledges"]:  # type: ignore
            if pledge != user:
                current_total += int(project["pledges"][pledge])  # type: ignore
        amount = project["total"] - current_total
    if percentage:
        amount = int(project["total"] * (int(amount) / 100))
    project["pledges"][user] = int(amount)
    write_project(id, project, user=False)

    # Open a slack conversation with the donor and get the channel ID
    r = app.client.conversations_open(users=user)  # type: ignore
    channel_id = r["channel"]["id"]  # type: ignore

    # Notify/thank the donor

    app.client.chat_postMessage(  # type: ignore
        channel=channel_id,  # type: ignore
        text=f'We\'ve updated your *total* pledge for "{project["title"]}" to ${amount}. Thank you for your support!\n\nOnce the project is fully funded I\'ll be in touch to arrange payment.',
    )

    # Check if the project has met its goal
    if check_if_funded(id=id):
        # Notify the admin channel
        app.client.chat_postMessage(  # type: ignore
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has met its funding goal!',
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f'"{project["title"]}" has met its funding goal!',
                    },
                    "accessory": {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Send invoices",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "sendInvoices",
                    },
                }
            ],
        )

        # Mark when the project was funded
        project["funded at"] = int(time.time())
        write_project(id, project, user=False)

    # Update all promotions
    message_blocks = display_project(id) + display_spacer() + display_donate(id)
    for promotion in project.get("promotions", []):
        app.client.chat_update(  # type: ignore
            channel=promotion["channel"],
            ts=promotion["ts"],
            blocks=message_blocks,
            text="A project was donated to",
        )

    # Update app home of donor first so they see the updated pledge faster
    update_home(user=user, client=app.client)

    # Update app homes of all donors
    for donor in project.get("pledges", {}):
        if donor != user:
            update_home(user=donor, client=app.client)

    # Send back an updated project block
    return display_project(id) + display_spacer() + display_donate(id)


def project_options(restricted: str | bool = False, approved: bool = False):
    projects = load_projects()
    options: list[dict[str, Any]] = []
    for project in projects:
        # Don't present funded projects as options
        if check_if_funded(id=project):
            continue

        # If only approved projects have been requested, skip unapproved projects
        if approved and not projects[project].get("approved", False):
            continue

        if restricted:
            if projects[project]["created by"] == restricted and not projects[
                project
            ].get("approved", False):
                options.append(
                    {
                        "text": {
                            "type": "plain_text",
                            "text": projects[project]["title"],
                        },
                        "value": project,
                    }
                )
        else:
            options.append(
                {
                    "text": {"type": "plain_text", "text": projects[project]["title"]},
                    "value": project,
                }
            )
    return options


def slack_id_shuffle(field: str, r: bool = False) -> str:
    # This function is used when we want to disable Slack's input preservation.
    if r:
        return field.split("SHUFFLE")[0]
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    return f"{field}SHUFFLE{random_string}"


def check_bad_currency(s: str) -> bool | str:
    try:
        int(s)
    except ValueError:
        return f"Donation pledges must be a number. `{s}` wasn't recognised."

    if int(s) < 1:
        return "Donation pledges must be a positive number."

    return False


def auth(client, user) -> bool:  # type: ignore
    r = client.usergroups_list(include_users=True)  # type: ignore
    groups: list[dict[str, Any]] = r.data["usergroups"]  # type: ignore
    for group in groups:  # type: ignore
        if group["id"] == config["admin_group"] and user in group["users"]:
            return True
    return False


def check_if_funded(
    raw_project: dict[str, Any] | None = None, id: str | None = None
) -> bool:
    if id and not raw_project:
        project: dict[str, Any] = get_project(id)
    elif raw_project == None:
        raise ValueError("No project provided to check_if_funded")
    else:
        project = raw_project

    current_pledges = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            current_pledges += int(project["pledges"][pledge])
    if current_pledges >= project["total"]:
        return True
    return False


def check_if_old(
    raw_project: dict[str, Any] | None = None, id: str | None = None
) -> bool:
    """Returns True if the project was funded more than age_out_threshold days ago"""
    if id and not raw_project:
        project: dict[str, Any] = get_project(id)
    elif raw_project == None:
        raise ValueError("No project provided to check_if_old")
    else:
        project = raw_project

    if "funded at" in project.keys():
        if (
            int(time.time()) - project["funded at"]
            > 86400 * config["age_out_threshold"]
        ):
            return True
        return False
    return True


def bool_to_emoji(b: bool) -> str:
    if b:
        return ":white_check_mark:"
    return ":x:"


#####################
# Display functions #
#####################


def construct_edit(project_id: str) -> list[dict[str, Any]]:
    project = get_project(project_id)
    if not project["img"]:
        project["img"] = ""
    edit_box = [
        {
            "type": "input",
            "block_id": slack_id_shuffle("title"),
            "element": {
                "type": "plain_text_input",
                "action_id": "plain_text_input-action",
                "initial_value": project["title"],
                "min_length": 6,
                "max_length": 64,
            },
            "label": {"type": "plain_text", "text": "Project Title", "emoji": True},
            "hint": {
                "type": "plain_text",
                "text": "The name of the project.",
                "emoji": True,
            },
        },
        {
            "type": "input",
            "block_id": slack_id_shuffle("total"),
            "element": {
                "type": "plain_text_input",
                "action_id": "plain_text_input-action",
                "initial_value": str(project["total"]),
            },
            "label": {"type": "plain_text", "text": "Total cost", "emoji": True},
            "hint": {
                "type": "plain_text",
                "text": "The estimated total cost of the project.",
                "emoji": True,
            },
        },
        {
            "type": "input",
            "block_id": slack_id_shuffle("desc"),
            "element": {
                "type": "plain_text_input",
                "action_id": "plain_text_input-action",
                "multiline": True,
                "initial_value": project["desc"],
                "min_length": 64,
                "max_length": 1000,
            },
            "label": {"type": "plain_text", "text": "Description", "emoji": True},
            "hint": {
                "type": "plain_text",
                "text": "A description of what the project is and why it would be helpful to the space. This is where you can really sell your project.",
                "emoji": True,
            },
        },
        {
            "type": "input",
            "block_id": slack_id_shuffle("img"),
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "plain_text_input-action",
                "initial_value": project["img"],
            },
            "label": {"type": "plain_text", "text": "Image", "emoji": True},
            "hint": {
                "type": "plain_text",
                "text": "[Optional] A URL to a promotional image for your app.",
                "emoji": True,
            },
        },
    ]

    # Add docs
    blocks = edit_box + display_spacer() + display_help("create", raw=False)  # type: ignore # When raw is False the return is always a list

    return blocks


def display_project(id: str, bar: bool = True) -> list[dict[str, Any]]:
    project = get_project(id)
    image = "https://github.com/Perth-Artifactory/branding/blob/main/artifactory_logo/png/Artifactory_logo_MARK-HEX_ORANG.png?raw=true"  # default image
    if project["img"]:
        image = project["img"]
    current_pledges = 0
    backers = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            backers += 1
            current_pledges += int(project["pledges"][pledge])
    if bar:
        bar_emoji = create_progress_bar(current_pledges, project["total"]) + " "
    else:
        bar_emoji = ""
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": format(project["title"]),
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f'{bar_emoji}${current_pledges}/${project["total"]} | {backers} backers\n'
                + f'{project["desc"]} \n'
                + f'*Created by*: <@{project["created by"]}> *Last updated by*: <@{project["last updated by"]}>',
            },
            "accessory": {
                "type": "image",
                "image_url": image,
                "alt_text": "Project image",
            },
        },
    ]

    return blocks


def display_project_details(project_id: str) -> list[dict[str, Any]]:
    project = get_project(project_id)

    current_pledges = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            current_pledges += int(project["pledges"][pledge])

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": format(project["title"]),
                "emoji": True,
            },
        }
    ]

    fields: dict[str, str] = {}

    # Approval
    fields["Approved"] = bool_to_emoji(project["approved"])
    if project.get("approved", False) and project.get("approved at", False):
        fields["Approved at"] = format_date(
            timestamp=project["approved at"], action="Approved at", raw=True
        )

    # Funding
    fields["Funded"] = bool_to_emoji(check_if_funded(project))
    if check_if_funded(project) and project.get("funded at", False):
        fields["Funded at"] = format_date(
            timestamp=project["funded at"], action="Funded at", raw=True
        )

    # Invoices sent
    fields["Invoices sent"] = bool_to_emoji(project.get("invoices_sent", False))
    if project.get("invoices_sent", False):
        fields["Invoices sent at"] = format_date(
            timestamp=project["invoices_sent"], action="Invoices sent at", raw=True
        )

    # Reconciled
    fields["Reconciled"] = bool_to_emoji(project.get("reconciled at", False))
    if project.get("reconciled at", False):
        fields["Reconciled at"] = format_date(
            timestamp=project["reconciled at"], action="Reconciled at", raw=True
        )

    # DGR
    fields["DGR"] = bool_to_emoji(project.get("dgr", False))

    # Promoted to
    if project.get("promotions", False):
        channels = ""
        for promotion in project["promotions"]:
            channels += f'<#{promotion["channel"]}> '
        fields["Promotions"] = channels

    # Generate field block
    field_blocks: list[dict[str, str | bool]] = []
    for field in fields:
        field_blocks.append({"type": "mrkdwn", "text": f"{field}: {fields[field]}"})

    # Add to block list
    blocks += [{"type": "section", "fields": field_blocks}]

    # Specific pledges
    blocks += display_spacer()
    blocks += display_header("Pledges:")
    text = ""
    for pledge in project["pledges"]:
        text += f'• <@{pledge}>: ${project["pledges"][pledge]}\n'
    text += f'\nTotal: ${current_pledges}/${project["total"]}\n'
    blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    return blocks


def display_approve(id: str) -> list[dict[str, Any]]:
    blocks = [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve project",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "approve",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve + DGR",
                        "emoji": True,
                    },
                    "style": "primary",
                    "value": id,
                    "action_id": "approve_as_dgr",
                },
            ],
        }
    ]
    return blocks


def display_create() -> list[dict[str, Any]]:
    blocks = [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Create a project",
                        "emoji": True,
                    },
                    "value": "AppHome",
                    "action_id": "create_from_home",
                }
            ],
        }
    ]
    return blocks


def display_admin_actions(id: str) -> list[dict[str, Any]]:
    blocks = [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Edit",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "edit_specific_project",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Details",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "project_details",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Unapprove",
                        "emoji": True,
                    },
                    "value": id,
                    "style": "danger",
                    "confirm": display_confirm(
                        title="Unapprove project",
                        text="Are you sure you want to unapprove this project? This will remove it from the public list of projects and prevent further donations.",
                        confirm="Yes, unapprove",
                        abort="No, keep it",
                    ),
                    "action_id": "unapprove",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Delete",
                        "emoji": True,
                    },
                    "style": "danger",
                    "confirm": display_confirm(
                        title="Delete project",
                        text="Are you sure you want to delete this project? This cannot be reversed.",
                        confirm="DELETE",
                        abort="No, keep it",
                    ),
                    "value": id,
                    "action_id": "delete",
                },
            ],
        }
    ]
    return blocks


def display_confirm(
    title: str = "Are you sure?",
    text: str = "Do you want to do this?",
    confirm: str = "Yes",
    abort: str = "No",
) -> dict[str, dict[str, str]]:
    blocks = {
        "title": {"type": "plain_text", "text": title},
        "text": {"type": "plain_text", "text": text},
        "confirm": {"type": "plain_text", "text": confirm},
        "deny": {"type": "plain_text", "text": abort},
    }

    return blocks


def display_donate(id: str, user: str | None = None, home: bool = False):
    home_add = ""
    if home:
        home_add = "_home"

    # Check if the project has met its goal
    if check_if_funded(id=id):
        blocks = [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "plain_text",
                        "text": "This project has met it's funding goal :heart: Thank you to everyone that donated.",
                        "emoji": True,
                    }
                ],
            }
        ]
    else:
        blocks = [
            {
                "dispatch_action": True,
                "block_id": slack_id_shuffle(id),
                "type": "input",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "donate_amount" + home_add,
                },
                "label": {
                    "type": "plain_text",
                    "text": "Donate specific amount",
                    "emoji": True,
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Donate 10%",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "donate10" + home_add,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Donate 20%",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "donate20" + home_add,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Donate the rest",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "donate_rest" + home_add,
                    },
                ],
            },
        ]
        project = get_project(id)
        if project.get("dgr", False):
            blocks += [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f'Donations to this project are considered gifts to {tidyhq_org["name"]} and are <{config["tax_info"]}|tax deductible>.',
                        }
                    ],
                }
            ]

    project = get_project(id)
    # This should really only be used in the App Home since it provides personalised results

    # Has the project received pledges?
    if "pledges" in project.keys():
        # Check if the user has already donated to this project
        if user in project["pledges"]:
            if check_if_funded(id=id):
                try:
                    blocks[0]["elements"][0]["text"] += f' Thank you for your ${project["pledges"][user]} donation!'  # type: ignore
                except KeyError:
                    raise Exception("Blocks malformed")
            else:
                # Prefill their existing donation amount.
                try:
                    blocks[0]["element"]["initial_value"] = str(project["pledges"][user])  # type: ignore
                except KeyError:
                    raise Exception("Blocks malformed")
                blocks += [
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "plain_text",
                                "text": f'Thanks for your ${ project["pledges"][user]} donation! You can update your pledge using the buttons above.',
                                "emoji": True,
                            }
                        ],
                    }
                ]

    return blocks


def display_edit_load(project_id: str | bool) -> list[dict[str, Any]]:
    box = [
        {
            "type": "actions",
            "block_id": "projectDropdown",
            "elements": [
                {
                    "type": "external_select",
                    "action_id": "project_selector",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a project to update",
                    },
                    "min_query_length": 0,
                }
            ],
        }
    ]
    if project_id and isinstance(project_id, str):
        project: dict[str, Any] = get_project(project_id)
        initial = {
            "text": {"text": project["title"], "type": "plain_text"},
            "value": project_id,
        }
        try:
            box[0]["elements"][0]["initial_option"] = initial  # type: ignore
        except KeyError:
            raise Exception("Blocks malformed")
    return box


def display_detail_button(id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Details",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "project_details",
                }
            ],
        }
    ]


def display_promote_button(id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Promote",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "promote_specific_project_entry",
                }
            ],
        }
    ]


def display_spacer():
    return [{"type": "divider"}]


def display_header(s: str) -> list[dict[str, Any]]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": s, "emoji": True}}
    ]


def display_promote() -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    help_text = display_help("promote", raw=False)
    if isinstance(help_text, list):
        blocks += help_text

    blocks = [
        {
            "type": "input",
            "element": {
                "type": "conversations_select",
                "filter": {"include": ["public"]},
                "initial_conversation": "C0LQBEQ2Y",
            },
            "label": {
                "type": "plain_text",
                "text": "Pick a public channel",
                "emoji": True,
            },
            "optional": False,
        }
    ]

    return blocks


# this will be inaccurate if segments * 4 + 2 is not a whole number
def create_progress_bar(current: int | float, total: int, segments: int = 7) -> str:
    segments = segments * 4 + 2
    if current == 0:
        filled = 0
    else:
        percent = 100 * float(current) / float(total)
        percentage_per_segment = 100.0 / segments
        if percent < percentage_per_segment:
            filled = 1
        elif 100 - percent < percentage_per_segment:
            filled = segments
        else:
            filled = round(percent / percentage_per_segment)
    s = "g" * filled + "w" * (segments - filled)
    final_s = ""

    # Add the starting cap
    final_s += f":pb-{s[0]}-a:"
    s = s[1:]

    # Fill the middle
    while len(s) > 1:
        final_s += f":pb-{s[:4]}:"
        s = s[4:]

    # Add the ending cap
    final_s += f":pb-{s[0]}-z:"

    return final_s


def format_date(timestamp: int, action: str, raw: bool = False) -> str:
    if raw:
        # Some fields do not accept Slack's date formatting
        return f"{str(datetime.fromtimestamp(timestamp))}"
    return f"<!date^{timestamp}^{action} {{date_pretty}}|{action} {str(datetime.fromtimestamp(timestamp))}>"


def display_home_projects(user: str, client: WebClient) -> list[dict[str, Any]]:
    projects = load_projects()

    blocks: list[dict[str, Any]] = []

    # Let admins know that they're seeing extra stuff on this page
    if auth(user=user, client=client):
        blocks += [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f':warning: As a member of <!subteam^{config["admin_group"]}> you have some extra options available to you. Please use them responsibly and assume that *donor information is confidential* unless the donor has explicitly stated otherwise.',
                },
            }
        ]

    blocks += display_header("Projects seeking donations")
    blocks += [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Everyone has different ideas about what the space needs. These are some of the projects currently seeking donations.",
            },
        }
    ]

    for project in projects:
        if projects[project].get("approved", False) and not check_if_funded(id=project):
            blocks += display_project(project)
            blocks += display_donate(project, user=user, home=True)
            blocks += display_promote_button(id=project)
            if auth(user=user, client=client):
                blocks += display_admin_actions(project)
            blocks += display_spacer()

    blocks += display_header("Recently funded projects")
    for project in projects:
        if check_if_funded(id=project) and not check_if_old(id=project):
            blocks += display_project(project, bar=False)
            if auth(user=user, client=client):
                blocks += display_detail_button(id=project)
            blocks += display_spacer()

    if auth(user=user, client=client):
        not_yet_approved: list[str] = []
        for project in projects:
            if not projects[project].get("approved", False):
                not_yet_approved.append(project)

        blocks += display_header("Projects awaiting approval")

        if len(not_yet_approved) > 0:
            for project in not_yet_approved:
                blocks += display_project(project)
                blocks += display_approve(project)
                blocks += display_spacer()

        else:
            blocks += display_help("no_projects_in_queue", raw=False)  # type: ignore # When raw is False the return is always a list
    else:
        not_yet_approved: list[str] = []
        for project in projects:
            if (
                not projects[project].get("approved", False)
                and projects[project]["created by"] == user
            ):
                not_yet_approved.append(project)

        if len(not_yet_approved) > 0:
            blocks += display_header("Your projects awaiting approval")
            blocks += [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain_text",
                            "text": str(display_help("personal_unapproved", raw=True)),
                            "emoji": True,
                        }
                    ],
                }
            ]
            for project in not_yet_approved:
                blocks += display_project(project)
                blocks += [
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Edit project",
                                    "emoji": True,
                                },
                                "value": project,
                                "action_id": "edit_specific_project",
                            },
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "Request approval",
                                    "emoji": True,
                                },
                                "value": project,
                                "style": "primary",
                                "confirm": display_confirm(
                                    title="Request Approval",
                                    text=str(display_help("approval", raw=True)),
                                    confirm="Request approval",
                                    abort="Cancel",
                                ),
                                "action_id": "request_project_approval",
                            },
                        ],
                    }
                ]
                blocks += display_spacer()
    return blocks  # type: ignore # Every instance of display_help used in this function returns a list


def display_help(article: str, raw: bool = False) -> str | list[dict[str, Any]]:
    articles: dict[str, str] = {}
    articles["create_CTA"] = (
        "Our space is entirely community driven. If you have an idea for a project that would benefit the space you can create it here."
    )
    articles[
        "create"
    ] = """The most successful projects tend to include the following things:
    • A useful title
    • A description that explains what the project is and why it would benefit the space. Instead of going into the minutiae provide a slack channel or wiki url where users can find more info for themselves.
    • A pretty picture. Remember pictures are typically displayed quite small so use them as an attraction rather than a method to convey detailed information. If you opt not to include an image we'll use a placeholder :artifactory2: instead.
    
    Once your project has been created it will need to be approved before people can donate to it. You can trigger the approval process by pressing the request button attached to your project."""
    articles["approval"] = (
        "Once your project has been approved you won't be able to edit it. If you need to make changes after this point you'll need to ask a committee member to perform them on your behalf."
    )
    articles[
        "promote"
    ] = """This will share the project to a public channel of your choosing.
    
For channels dedicated to a particular project you could pin the message as an easy way of reminding people that they can donate.
    
We also suggest actively talking about your project in the most relevant channel. eg, If you want to purchase a new 3D printer then <#CG05N75DZ> would be the best place to generate hype."""
    articles["personal_unapproved"] = (
        'These are projects you have created that haven\'t been approved yet. Press the "Request approval" button once your project is ready to go.'
    )
    articles["no_projects_in_queue"] = "There are no projects awaiting approval."

    if article not in articles.keys():
        articles[article] = " "

    if raw:
        return articles[article]

    return [{"type": "section", "text": {"type": "mrkdwn", "text": articles[article]}}]


######################
# Listener functions #
######################

# Initialise slack

app = App(token=config["SLACK_BOT_TOKEN"])

### Actions ###


def update_home(user: str, client: WebClient) -> None:
    home_view = {  # type: ignore # When raw is False the return is always a list
        "type": "home",
        "blocks": display_home_projects(client=client, user=user) + display_header("How to create a project") + display_help("create_CTA", raw=False) + display_create(),  # type: ignore # When raw is False the return is always a list
    }

    client.views_publish(user_id=user, view=home_view)  # type: ignore


@app.view("update_data")  # type: ignore
def update_data(ack, body: dict[str, Any], client: WebClient):  # type: ignore
    data = body["view"]["state"]["values"]
    if "private_metadata" in body["view"].keys():
        project_id = body["view"]["private_metadata"]
    else:
        project_id = body["view"]["state"]["values"]["projectDropdown"][
            "project_selector"
        ]["selected_option"][
            "value"
        ]  # Gotta be an easier way

    user = body["user"]["id"]
    # Validation
    errors = {}

    total_shuffled = False

    # Find our slack_id_shuffle'd field
    for field in data:
        if slack_id_shuffle(field, r=True) == "total":
            total_shuffled = field

    if not total_shuffled:
        # This should never happen
        pass

    # Is cost a number

    total = data[total_shuffled]["plain_text_input-action"]["value"].replace("$", "")
    if check_bad_currency(total):
        errors[total_shuffled] = check_bad_currency(total)
        ack({"response_action": "errors", "errors": errors})
        return False
    else:
        total = int(total)
        ack()

    # Get existing project info
    project = get_project(project_id)

    for v in data:
        # Slack preserves field input when updating a view based on IDs. Because this cannot be disabled we add junk data to each ID to confuse slack.
        v_clean = slack_id_shuffle(v, r=True)
        if v_clean == "total":
            project[v_clean] = total
        else:
            if "plain_text_input-action" in data[v].keys():
                project[v_clean] = data[v]["plain_text_input-action"]["value"]
    write_project(project_id, project, user)
    update_home(user=user, client=client)


@app.view("promote_project")  # type: ignore
def promote_project(ack, body: dict[str, Any]):  # type: ignore
    ack()
    project_id = body["view"]["private_metadata"]

    # Channel id we need is double nested inside two dicts with random keys.
    values = body["view"]["state"]["values"]
    i: str = next(iter(values))
    i2: str = next(iter(values[i]))
    channel: str = values[i][i2]["selected_conversation"]

    title = get_project(project_id)["title"]

    # Add promoting as a separate message so it can be removed by a Slack admin if desired. (ie when promoted as part of a larger post)
    app.client.chat_postMessage(  # type: ignore
        channel=channel,
        text=f'<@{body["user"]["id"]}> has promoted a project, check it out!',
    )
    promo_msg = app.client.chat_postMessage(  # type: ignore
        channel=channel,
        blocks=display_project(project_id)
        + display_spacer()
        + display_donate(project_id),
        text=f"Check out our fundraiser for: {title}",
    )

    # Log this promotion message
    log_promotion(project_id=project_id, slack_response=promo_msg)


@app.action("project_selector")  # type: ignore
def project_selected(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id = body["view"]["state"]["values"]["projectDropdown"]["project_selector"][
        "selected_option"
    ]["value"]
    view_id = body["container"]["view_id"]
    client.views_update(  # type: ignore
        view_id=view_id,
        view={
            "type": "modal",
            # View identifier
            "callback_id": "update_data",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },  # project["title"]
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": construct_edit(project_id=project_id),
            "private_metadata": project_id,
        },
    )


@app.action("edit_specific_project")  # type: ignore
def edit_specific_project(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()

    project_id = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "update_data",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": construct_edit(project_id=project_id),
            "private_metadata": project_id,
        },
    )


# Donate buttons with inline update


@app.action("donate10")  # type: ignore
def donate10(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, 10, user, percentage=True)


@app.action("donate20")  # type: ignore
def donate20(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, 20, user, percentage=True)


@app.action("donate_rest")  # type: ignore
def donate_rest(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, "remaining", user)


@app.action("donate_amount")  # type: ignore
def donate_amount(ack, body: dict[str, Any], respond) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id = slack_id_shuffle(field=body["actions"][0]["block_id"], r=True)
    amount: str = body["actions"][0]["value"]
    if check_bad_currency(amount):
        respond(
            text=check_bad_currency(amount),
            replace_original=False,
            response_type="ephemeral",
        )
    else:
        pledge(project_id, amount, user)


# Donate buttons with home update


@app.action("donate10_home")  # type: ignore
def donate10_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, 10, user, percentage=True)


@app.action("donate20_home")  # type: ignore
def donate20_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, 20, user, percentage=True)


@app.action("donate_rest_home")  # type: ignore
def donate_rest_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = body["actions"][0]["value"]
    pledge(project_id, "remaining", user)


@app.action("donate_amount_home")  # type: ignore
def donate_amount_home(ack, body: dict[str, Any], client: WebClient, say) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    project_id: str = slack_id_shuffle(field=body["actions"][0]["block_id"], r=True)
    amount: str = body["actions"][0]["value"]
    if check_bad_currency(amount):
        say(text=check_bad_currency(amount), channel=user)
    else:
        pledge(project_id, amount, user)


@app.action("conversation_selector")  # type: ignore
def conversation_selector(ack) -> None:  # type: ignore
    ack()
    # we actually don't want to do anything yet


@app.action("project_preview_selector")  # type: ignore
def project_preview_selector(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    view_id: str = body["container"]["view_id"]

    view = {
        "title": {"type": "plain_text", "text": "Promote project", "emoji": True},
        "submit": {"type": "plain_text", "text": "Promote!", "emoji": True},
        "type": "modal",
        "blocks": display_promote(),
    }
    # callback promote_project
    client.views_update(  # type: ignore
        view_id=view_id,
        view=view,
    )


@app.action("promote_specific_project_entry")  # type: ignore
def promote_specific_project_entry(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "promote_project",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": display_promote(),
            "private_metadata": project_id,
        },
    )


@app.action("promote_from_home")  # type: ignore
def promote_from_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "promote_project",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": display_promote(),
        },
    )


@app.action("update_from_home")  # type: ignore
def update_from_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "loadProject",
            "title": {"type": "plain_text", "text": "Select Project"},
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": display_edit_load(project_id=False),
        },
    )


@app.action("create_from_home")  # type: ignore
def create_from_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    # pick a new id
    project_id: str = "".join(
        random.choices(string.ascii_letters + string.digits, k=16)
    )
    while project_id in load_projects().keys():
        project_id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            # View identifier
            "callback_id": "update_data",
            "title": {"type": "plain_text", "text": "Create a pledge"},
            "submit": {"type": "plain_text", "text": "Create!"},
            "private_metadata": project_id,
            "blocks": construct_edit(project_id=project_id),
        },
    )


@app.action("approve")  # type: ignore
def approve(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = get_project(project_id)

    # Projects approved in this function should be marked as DGR ineligible
    project["dgr"] = False

    project["approved"] = True
    project["approved_at"] = int(time.time())
    write_project(project_id, project, user=False)

    # Open a slack conversation with the creator and get the channel ID
    r = app.client.conversations_open(users=project["created by"])  # type: ignore
    channel_id: str = str(r["channel"]["id"])  # type: ignore

    # Notify the creator
    app.client.chat_postMessage(  # type: ignore
        channel=channel_id,
        text=f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice.',
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice.',
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Promote",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "promote_specific_project_entry",
                },
            }
        ],
    )

    # Check container type

    # Coming from a modal, typically home
    if body["container"]["type"] == "view":
        # Send a notification to the admin channel
        app.client.chat_postMessage(  # type: ignore
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has been approved by <@{user}>.',
        )

    # Coming from a message, which means we can just update that message
    elif body["container"]["type"] == "message":
        # Take out the approval buttons
        blocks: list[dict[str, Any]] = body["message"]["blocks"][:-1]
        blocks += [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"<@{user}> approved this project"}
                ],
            }
        ]

        app.client.chat_update(  # type: ignore
            channel=body["container"]["channel_id"],
            ts=body["container"]["message_ts"],
            blocks=blocks,
            text=f"Project approved by <@{user}>",
            as_user=True,
        )

    update_home(user=user, client=client)


@app.action("approve_as_dgr")  # type: ignore
def approve_as_dgr(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = get_project(project_id)
    project["approved"] = True
    project["approved_at"] = int(time.time())
    project["dgr"] = True
    write_project(project_id, project, user=False)

    # Open a slack conversation with the creator and get the channel ID
    r = app.client.conversations_open(users=project["created by"])  # type: ignore
    channel_id: str = str(r["channel"]["id"])  # type: ignore

    # Notify the creator
    app.client.chat_postMessage(  # type: ignore
        channel=channel_id,
        text=f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice. Additionally, we have marked this project as qualifying for <{config["tax_info"]}|tax deductible donations>.',
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice.\nAdditionally, we have marked this project as qualifying for <{config["tax_info"]}|tax deductible donations>.',
                },
                "accessory": {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Promote",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "promote_specific_project_entry",
                },
            }
        ],
    )

    # Check container type

    # Coming from a modal, typically home
    if body["container"]["type"] == "view":
        # Send a notification to the admin channel
        app.client.chat_postMessage(  # type: ignore
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has been marked as tax deductible and approved by <@{user}>.',
        )

    # Coming from a message, which means we can just update that message
    elif body["container"]["type"] == "message":
        # Take out the approval buttons
        blocks: list[dict[str, Any]] = body["message"]["blocks"][:-1]
        blocks += [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"<@{user}> marked this as tax deductible and approved",
                    }
                ],
            }
        ]

        app.client.chat_update(  # type: ignore
            channel=body["container"]["channel_id"],
            ts=body["container"]["message_ts"],
            blocks=blocks,
            text=f"Project approved by <@{user}>",
            as_user=True,
        )

    update_home(user=user, client=client)


@app.action("unapprove")  # type: ignore
def unapprove(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]

    unapprove_project(project_id)

    update_home(user=user, client=client)


@app.action("delete")  # type: ignore
def delete(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]

    delete_project(project_id)

    update_home(user=user, client=client)


@app.action("project_details")  # type: ignore
def project_details(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Project Details"},
            "blocks": display_project_details(project_id=project_id),
        },
    )


@app.action("sendInvoices")  # type: ignore
def invoice(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = get_project(project_id)

    # Get reply method
    # Coming from a modal, typically home
    if body["container"]["type"] == "view":
        # Send a notification to the admin channel
        r = app.client.chat_postMessage(  # type: ignore
            channel=config["admin_channel"],
            text=f'Invoicing for "{project["title"]}" has been triggered by <@{user}>.',
        )

        reply = r["ts"]  # type: ignore
        blocks = []
        button = {}

    # Coming from a message, which means we can just update that message
    elif body["container"]["type"] == "message":
        reply = body["container"]["message_ts"]

        # Store the generate invoice button in case we need to re-add it
        blocks: list[dict[str, Any]] = body["message"]["blocks"]
        # Check for accessory button in the last block
        if "accessory" in blocks[-1].keys():
            button = blocks[-1]["accessory"]
            # Remove just the accessory
            blocks[-1].pop("accessory")
        # Strip newlines from the text field in the last block
        blocks[-1]["text"]["text"] = blocks[-1]["text"]["text"].replace("\n", "")
        blocks += [
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Invoicing has been triggered by <@{user}>.",
                    }
                ],
            }
        ]

        app.client.chat_update(  # type: ignore
            channel=body["container"]["channel_id"],
            ts=body["container"]["message_ts"],
            blocks=blocks,
            text=f"Invoicing started by <@{user}>",
            as_user=True,
        )

    else:
        raise Exception("Could not get reply method for invoicing")

    # Initiate the invoice process
    outcome: str = utils.project_output.send_invoices_lib(project_id)
    sent: bool = True if "Error:" not in outcome[:6] else False

    # If we came from a message we can add the trigger button back in if the invoicing failed
    if body["container"]["type"] == "message":
        # If we weren't successful, add the button back at the bottom
        if not sent:
            blocks[0]["accessory"] = button  # type: ignore

            app.client.chat_update(  # type: ignore
                channel=body["container"]["channel_id"],
                ts=body["container"]["message_ts"],
                blocks=blocks,
                text=f"Invoicing started by <@{user}>",
                as_user=True,
            )

    else:
        raise Exception("Unknown container type")

    # Add invoicing details as reply to the notification
    app.client.chat_postMessage(  # type: ignore
        channel=config["admin_channel"], thread_ts=reply, text=outcome  # type: ignore
    )


@app.action("request_project_approval")  # type: ignore
def request_project_approval(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = get_project(project_id)

    # Send prompt to admins
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f'"{project["title"]}" has been submitted for approval by <@{user}>. Please review the project.',
            },
        }
    ]
    blocks += display_project(project_id)
    blocks += display_approve(project_id)

    app.client.chat_postMessage(  # type: ignore
        channel=config["admin_channel"],
        text=f'<@{user}> has requested approval for "{project["title"]}".',
        blocks=blocks,
    )

    # Open a slack conversation with the creator and get the channel ID
    r: SlackResponse = app.client.conversations_open(users=project["created by"])  # type: ignore
    channel_id: str = str(r["channel"]["id"])  # type: ignore

    # Notify the creator
    app.client.chat_postMessage(  # type: ignore
        channel=channel_id,
        text=f'Your project "{project["title"]}" has been submitted for approval.',
    )

    update_home(user=user, client=client)


### info ###


@app.options("project_selector")  # type: ignore
def project_selector(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    if auth(user=body["user"]["id"], client=client):
        ack(options=project_options())
    else:
        ack(options=project_options(restricted=body["user"]["id"], approved=False))


@app.options("project_preview_selector")  # type: ignore
def project_preview_selector_opt(ack) -> None:  # type: ignore
    ack(options=project_options(approved=True))


# Update the app home
@app.event("app_home_opened")  # type: ignore
def app_home_opened(event: dict[str, Any], client: WebClient) -> None:
    update_home(user=event["user"], client=client)


# Get TidyHQ org details
tidyhq_org: dict[str, Any] = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": config["tidyhq_token"]},
).json()

# Start listening for commands
if __name__ == "__main__":
    SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()
