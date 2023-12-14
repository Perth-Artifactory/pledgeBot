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
def loadProjects():
    with open("projects.json", "r") as f:
        return json.load(f)


# Update project, data should be an entire project initially pulled with getProject
def writeProject(id: str, data: dict[str, Any], user: str | bool):
    projects = loadProjects()
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
                text=f"Old:\n```{json.dumps(loadProjects()[id], indent=4, sort_keys=True)}```",
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


def getProject(id: str) -> dict[str, Any]:
    projects = loadProjects()
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


def unapproveProject(id: str) -> None:
    project = getProject(id)
    project["approved"] = False
    writeProject(id, project, user=False)


def logPromotion(id: str, slack_response: SlackResponse) -> None:
    project = getProject(id)
    if "promotions" not in project.keys():
        project["promotions"] = []
    # Construct tuple of channel and timestamp
    promotion: list[str] = [slack_response["channel"], slack_response["ts"]]  # type: ignore
    project["promotions"].append( # type: ignore
        {"channel": slack_response["channel"], "ts": slack_response["ts"]}
    )
    writeProject(id, project, user=False)


def deleteProject(id: str) -> None:
    projects = loadProjects()
    del projects[id]
    with open("projects.json", "w") as f:
        json.dump(projects, f, indent=4, sort_keys=True)


def validateId(id: str) -> bool:
    allowed = set(string.ascii_letters + string.digits + "_" + "-")
    if set(id) <= allowed:
        return True
    return False


def pledge(
    id: str, amount: int | str, user: str, percentage: bool = False
) -> list[dict[str, Any]]:
    project: dict[str, Any] = loadProjects()[id]
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
    writeProject(id, project, user=False)

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
        writeProject(id, project, user=False)

    # Update all promotions
    message_blocks = displayProject(id) + displaySpacer() + displayDonate(id)
    for promotion in project.get("promotions",[]):
        app.client.chat_update( # type: ignore
            channel=promotion["channel"],
            ts=promotion["ts"],
            blocks=message_blocks,
            text="A project was donated to")

    # Update app home of donor first so they see the updated pledge faster
    updateHome(user=user, client=app.client)

    # Update app homes of all donors
    for donor in project.get("pledges",{}):
        if donor != user:
            updateHome(user = donor, client = app.client)

    # Send back an updated project block
    return displayProject(id) + displaySpacer() + displayDonate(id)


def projectOptions(restricted: str | bool = False, approved: bool = False):
    projects = loadProjects()
    options: list[dict[str, Any]] = []
    for project in projects:
        # Don't present funded projects as options
        if check_if_funded(id=project):
            continue

        # If only approved projects have been requested, skip unapproved projects
        if approved:
            if not projects[project].get("approved", False):
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


def slackIdShuffle(field: str, r: bool = False) -> str:
    # This function is used when we want to disable Slack's input preservation.
    if r:
        return field.split("SHUFFLE")[0]
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    return f"{field}SHUFFLE{random_string}"


def checkBadCurrency(s: str) -> bool | str:
    try:
        int(s)
    except ValueError:
        return f"Donation pledges must be a number. `{s}` wasn't recognised."

    if int(s) < 1:
        return "Donation pledges must be a positive number."

    return False


def auth(client, user) -> bool:  # type: ignore
    r = app.client.usergroups_list(include_users=True)  # type: ignore
    groups: list[dict[str, Any]] = r.data["usergroups"]  # type: ignore
    for group in groups:  # type: ignore
        if group["id"] == config["admin_group"]:
            if user in group["users"]:
                return True
    return False


def check_if_funded(
    raw_project: dict[str, Any] | None = None, id: str | None = None
) -> bool:
    if id and not raw_project:
        project: dict[str, Any] = getProject(id)
    elif raw_project == None:
        raise Exception("No project provided to check_if_funded")
    else:
        project = raw_project

    currentp = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            currentp += int(project["pledges"][pledge])
    if currentp >= project["total"]:
        return True
    return False


def check_if_old(
    raw_project: dict[str, Any] | None = None, id: str | None = None
) -> bool:
    """Returns True if the project was funded more than age_out_threshold days ago"""
    if id and not raw_project:
        project: dict[str, Any] = getProject(id)
    elif raw_project == None:
        raise Exception("No project provided to check_if_old")
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


def boolToEmoji(b: bool) -> str:
    if b:
        return ":white_check_mark:"
    return ":x:"


#####################
# Display functions #
#####################


def constructEdit(id: str) -> list[dict[str, Any]]:
    project = getProject(id)
    if not project["img"]:
        project["img"] = ""
    editbox = [
        {
            "type": "input",
            "block_id": slackIdShuffle("title"),
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
            "block_id": slackIdShuffle("total"),
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
            "block_id": slackIdShuffle("desc"),
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
            "block_id": slackIdShuffle("img"),
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
    # Deprecated selector to pick a project to edit
    # if project["desc"]:
    #    editbox = displayEditLoad(id) + displaySpacer() + editbox

    # Add docs
    blocks = editbox + displaySpacer() + displayHelp("create", raw=False)  # type: ignore # When raw is False the return is always a list

    return blocks  # type: ignore


def displayProject(id: str, bar: bool = True) -> list[dict[str, Any]]:
    project = getProject(id)
    image = "https://github.com/Perth-Artifactory/branding/blob/main/artifactory_logo/png/Artifactory_logo_MARK-HEX_ORANG.png?raw=true"  # default image
    if project["img"]:
        image = project["img"]
    currentp = 0
    backers = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            backers += 1
            currentp += int(project["pledges"][pledge])
    if bar:
        bar_emoji = createProgressBar(currentp, project["total"]) + " "
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
                "text": f'{bar_emoji}${currentp}/${project["total"]} | {backers} backers\n'
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


def displayProjectDetails(id: str) -> list[dict[str, Any]]:
    project = getProject(id)

    currentp = 0
    backers = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            backers += 1
            currentp += int(project["pledges"][pledge])

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
    fields["Approved"] = boolToEmoji(project["approved"])
    if project.get("approved", False) and project.get("approved at", False):
        fields["Approved at"] = formatDate(
            timestamp=project["approved at"], action="Approved at", raw=True
        )

    # Funding
    fields["Funded"] = boolToEmoji(check_if_funded(project))
    if check_if_funded(project) and project.get("funded at", False):
        fields["Funded at"] = formatDate(
            timestamp=project["funded at"], action="Funded at", raw=True
        )

    # Invoices sent
    fields["Invoices sent"] = boolToEmoji(project.get("invoices_sent", False))
    if project.get("invoices_sent", False):
        fields["Invoices sent at"] = formatDate(
            timestamp=project["invoices_sent"], action="Invoices sent at", raw=True
        )

    # DGR
    fields["DGR"] = boolToEmoji(project.get("dgr", False))
    
    # Promoted to
    if project.get("promotions", False):
        channels = ""
        for promotion in project["promotions"]:
            channels += f'<#{promotion["channel"]}> '
        fields["Promotions"] = channels

    # Generate field block
    field_blocks: list[dict[str, str | bool]] = []
    for field in fields:
        field_blocks.append(
            {"type": "mrkdwn", "text": f"{field}: {fields[field]}"}
        )

    # Add to block list
    blocks += [{"type": "section", "fields": field_blocks}]

    # Specific pledges
    blocks += displaySpacer()
    blocks += displayHeader("Pledges:")
    text = ""
    for pledge in project["pledges"]:
        text += f'• <@{pledge}>: ${project["pledges"][pledge]}\n'
    text += f'\nTotal: ${currentp}/${project["total"]}\n'
    blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

    return blocks


def displayApprove(id: str) -> list[dict[str, Any]]:
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


def displayCreate() -> list[dict[str, Any]]:
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
                    "action_id": "createFromHome",
                }
            ],
        }
    ]
    return blocks


def displayAdminActions(id: str) -> list[dict[str, Any]]:
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
                    "action_id": "editSpecificProject",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Details",
                        "emoji": True,
                    },
                    "value": id,
                    "action_id": "projectDetails",
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
                    "confirm": displayConfirm(
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
                    "confirm": displayConfirm(
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


def displayConfirm(
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


def displayDonate(id: str, user: str | None = None, home: bool = False):
    homeadd = ""
    if home:
        homeadd = "_home"

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
                "block_id": slackIdShuffle(id),
                "type": "input",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "donateAmount" + homeadd,
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
                        "action_id": "donate10" + homeadd,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Donate 20%",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "donate20" + homeadd,
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Donate the rest",
                            "emoji": True,
                        },
                        "value": id,
                        "action_id": "donateRest" + homeadd,
                    },
                ],
            },
        ]
        project = getProject(id)
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

    project = getProject(id)
    # This should really only be used in the App Home since it provides personalised results

    # Has the project received pledges?
    if "pledges" in project.keys():
        # Check if the user has already donated to this project
        if user in project["pledges"]:
            if check_if_funded(id=id):
                try:
                    blocks[0]["elements"][0]["text"] += f' Thank you for your ${project["pledges"][user]} donation!'  # type: ignore
                except:
                    raise Exception("Blocks malformed")
            else:
                # Prefill their existing donation amount.
                try:
                    blocks[0]["element"]["initial_value"] = str(project["pledges"][user])  # type: ignore
                except:
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


def displayEditLoad(id: str | bool) -> list[dict[str, Any]]:
    box = [
        {
            "type": "actions",
            "block_id": "projectDropdown",
            "elements": [
                {
                    "type": "external_select",
                    "action_id": "projectSelector",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a project to update",
                    },
                    "min_query_length": 0,
                }
            ],
        }
    ]
    if id and type(id) != bool:
        project: dict[str, Any] = getProject(id)
        initial = {
            "text": {"text": project["title"], "type": "plain_text"},
            "value": id,
        }
        try:
            box[0]["elements"][0]["initial_option"] = initial  # type: ignore
        except:
            raise Exception("Blocks malformed")
    return box


def displayDetailButton(id: str) -> list[dict[str, Any]]:
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
                    "action_id": "projectDetails",
                }
            ],
        }
    ]


def displayPromoteButton(id: str) -> list[dict[str, Any]]:
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
                    "action_id": "promoteSpecificProject_entry",
                }
            ],
        }
    ]


def displaySpacer():
    return [{"type": "divider"}]


def displayHeader(s: str) -> list[dict[str, Any]]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": s, "emoji": True}}
    ]


def displayPromote(id: str | bool = False) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    help = displayHelp("promote", raw=False)
    if type(help) == list:
        blocks += help

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
def createProgressBar(current: int | float, total: int, segments: int = 7) -> str:
    segments = segments * 4 + 2
    if current == 0:
        filled = 0
    else:
        percent = 100 * float(current) / float(total)
        percentagePerSegment = 100.0 / segments
        if percent < percentagePerSegment:
            filled = 1
        elif 100 - percent < percentagePerSegment:
            filled = segments
        else:
            filled = round(percent / percentagePerSegment)
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


def formatDate(timestamp: int, action: str, raw: bool = False) -> str:
    if raw:
        # Some fields do not accept Slack's date formatting
        return f"{str(datetime.fromtimestamp(timestamp))}"
    return f"<!date^{timestamp}^{action} {{date_pretty}}|{action} {str(datetime.fromtimestamp(timestamp))}>"


def displayHomeProjects(user: str, client: WebClient) -> list[dict[str, Any]]:
    projects = loadProjects()

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

    blocks += displayHeader("Projects seeking donations")
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
            blocks += displayProject(project)
            blocks += displayDonate(project, user=user, home=True)
            blocks += displayPromoteButton(id=project)
            if auth(user=user, client=client):
                blocks += displayAdminActions(project)
            blocks += displaySpacer()

    blocks += displayHeader("Recently funded projects")
    for project in projects:
        if check_if_funded(id=project) and not check_if_old(id=project):
            blocks += displayProject(project, bar=False)
            if auth(user=user, client=client):
                blocks += displayDetailButton(id=project)
            blocks += displaySpacer()

    if auth(user=user, client=client):
        not_yet_approved: list[str] = []
        for project in projects:
            if not projects[project].get("approved", False):
                not_yet_approved.append(project)

        blocks += displayHeader("Projects awaiting approval")

        if len(not_yet_approved) > 0:
            for project in not_yet_approved:
                blocks += displayProject(project)
                blocks += displayApprove(project)
                blocks += displaySpacer()

        else:
            blocks += displayHelp("no_projects_in_queue", raw=False)  # type: ignore # When raw is False the return is always a list
    else:
        not_yet_approved: list[str] = []
        for project in projects:
            if (
                not projects[project].get("approved", False)
                and projects[project]["created by"] == user
            ):
                not_yet_approved.append(project)

        if len(not_yet_approved) > 0:
            blocks += displayHeader("Your projects awaiting approval")
            blocks += [
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "plain_text",
                            "text": str(displayHelp("personal_unapproved", raw=True)),
                            "emoji": True,
                        }
                    ],
                }
            ]
            for project in not_yet_approved:
                blocks += displayProject(project)
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
                                "action_id": "editSpecificProject",
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
                                "confirm": displayConfirm(
                                    title="Request Approval",
                                    text=str(displayHelp("approval", raw=True)),
                                    confirm="Request approval",
                                    abort="Cancel",
                                ),
                                "action_id": "requestProjectApproval",
                            },
                        ],
                    }
                ]
                blocks += displaySpacer()
    return blocks  # type: ignore # Every instance of displayHelp used in this function returns a list


def displayHelp(article: str, raw: bool = False) -> str | list[dict[str, Any]]:
    articles: dict[str, str] = {}
    articles[
        "create_CTA"
    ] = "Our space is entirely community driven. If you have an idea for a project that would benefit the space you can create it here."
    articles[
        "create"
    ] = """The most successful projects tend to include the following things:
    • A useful title
    • A description that explains what the project is and why it would benefit the space. Instead of going into the minutiae provide a slack channel or wiki url where users can find more info for themselves.
    • A pretty picture. Remember pictures are typically displayed quite small so use them as an attraction rather than a method to convey detailed information. If you opt not to include an image we'll use a placeholder :artifactory2: instead.
    
    Once your project has been created it will need to be approved before people can donate to it. You can trigger the approval process by pressing the request button attached to your project."""
    articles[
        "approval"
    ] = "Once your project has been approved you won't be able to edit it. If you need to make changes after this point you'll need to ask a committee member to perform them on your behalf."
    articles[
        "promote"
    ] = """This will share the project to a public channel of your choosing.
    
For channels dedicated to a particular project you could pin the message as an easy way of reminding people that they can donate.
    
We also suggest actively talking about your project in the most relevant channel. eg, If you want to purchase a new 3D printer then <#CG05N75DZ> would be the best place to generate hype."""
    articles[
        "personal_unapproved"
    ] = 'These are projects you have created that haven\'t been approved yet. Press the "Request approval" button once your project is ready to go.'
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


def updateHome(user: str, client: WebClient) -> None:
    home_view = {  # type: ignore # When raw is False the return is always a list
        "type": "home",
        "blocks": displayHomeProjects(client=client, user=user) + displayHeader("How to create a project") + displayHelp("create_CTA", raw=False) + displayCreate(),  # type: ignore # When raw is False the return is always a list
    }

    client.views_publish(user_id=user, view=home_view)  # type: ignore


@app.view("updateData")  # type: ignore
def updateData(ack, body: dict[str, Any], client: WebClient):  # type: ignore
    data = body["view"]["state"]["values"]
    if "private_metadata" in body["view"].keys():
        id = body["view"]["private_metadata"]
    else:
        id = body["view"]["state"]["values"]["projectDropdown"]["projectSelector"][
            "selected_option"
        ][
            "value"
        ]  # Gotta be an easier way

    user = body["user"]["id"]
    # Validation
    errors = {}

    total_shuffled = False

    # Find our slackIdShuffle'd field
    for field in data:
        if slackIdShuffle(field, r=True) == "total":
            total_shuffled = field

    if not total_shuffled:
        # This should never happen
        pass

    # Is cost a number

    total = data[total_shuffled]["plain_text_input-action"]["value"].replace("$", "")
    if checkBadCurrency(total):
        errors[total_shuffled] = checkBadCurrency(total)
        ack({"response_action": "errors", "errors": errors})
        return False
    else:
        total = int(total)
        ack()

    # Get existing project info
    project = getProject(id)

    for v in data:
        # Slack preserves field input when updating a view based on IDs. Because this cannot be disabled we add junk data to each ID to confuse slack.
        v_clean = slackIdShuffle(v, r=True)
        if v_clean == "total":
            project[v_clean] = total
        else:
            if "plain_text_input-action" in data[v].keys():
                project[v_clean] = data[v]["plain_text_input-action"]["value"]
    writeProject(id, project, user)
    updateHome(user=user, client=client)


@app.view("promoteProject")  # type: ignore
def promoteProject(ack, body: dict[str, Any]):  # type: ignore
    ack()
    id = body["view"]["private_metadata"]

    # Channel id we need is double nested inside two dicts with random keys.
    values = body["view"]["state"]["values"]
    i: str = next(iter(values))
    i2: str = next(iter(values[i]))
    channel: str = values[i][i2]["selected_conversation"]

    title = getProject(id)["title"]

    # Add promoting as a separate message so it can be removed by a Slack admin if desired. (ie when promoted as part of a larger post)
    app.client.chat_postMessage(  # type: ignore
        channel=channel,
        text=f'<@{body["user"]["id"]}> has promoted a project, check it out!',
    )
    promo_msg = app.client.chat_postMessage(  # type: ignore
        channel=channel,
        blocks=displayProject(id) + displaySpacer() + displayDonate(id),
        text=f"Check out our fundraiser for: {title}",
    )

    # Log this promotion message
    logPromotion(id=id, slack_response=promo_msg)


@app.action("projectSelector")  # type: ignore
def projectSelected(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id = body["view"]["state"]["values"]["projectDropdown"]["projectSelector"][
        "selected_option"
    ]["value"]
    # id = body["actions"][0]["selected_option"]["value"]
    view_id = body["container"]["view_id"]
    client.views_update(  # type: ignore
        view_id=view_id,
        view={
            "type": "modal",
            # View identifier
            "callback_id": "updateData",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },  # project["title"]
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": constructEdit(id=id),
            "private_metadata": id,
        },
    )


@app.action("editSpecificProject")  # type: ignore
def editSpecificProject(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()

    id = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "updateData",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": constructEdit(id=id),
            "private_metadata": id,
        },
    )


# Donate buttons with inline update


@app.action("donate10")  # type: ignore
def donate10(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, 10, user, percentage=True)


@app.action("donate20")  # type: ignore
def donate20(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, 20, user, percentage=True)


@app.action("donateRest")  # type: ignore
def donateRest(ack, body: dict[str, Any]) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, "remaining", user)


@app.action("donateAmount")  # type: ignore
def donateAmount(ack, body: dict[str, Any], respond) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id = slackIdShuffle(field=body["actions"][0]["block_id"], r=True)
    amount: str = body["actions"][0]["value"]
    if checkBadCurrency(amount):
        respond(
            text=checkBadCurrency(amount),
            replace_original=False,
            response_type="ephemeral",
        )
    else:
        pledge(id, amount, user)


# Donate buttons with home update


@app.action("donate10_home")  # type: ignore
def donate10_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, 10, user, percentage=True)


@app.action("donate20_home")  # type: ignore
def donate20_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, 20, user, percentage=True)


@app.action("donateRest_home")  # type: ignore
def donateRest_home(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = body["actions"][0]["value"]
    pledge(id, "remaining", user)


@app.action("donateAmount_home")  # type: ignore
def donateAmount_home(ack, body: dict[str, Any], client: WebClient, say) -> None:  # type: ignore
    ack()
    user: str = body["user"]["id"]
    id: str = slackIdShuffle(field=body["actions"][0]["block_id"], r=True)
    amount: str = body["actions"][0]["value"]
    if checkBadCurrency(amount):
        say(text=checkBadCurrency(amount), channel=user)
    else:
        pledge(id, amount, user)


@app.action("conversationSelector")  # type: ignore
def conversationSelector(ack) -> None:  # type: ignore
    ack()
    # we actually don't want to do anything yet


@app.action("projectPreviewSelector")  # type: ignore
def projectPreviewSelector(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    view_id: str = body["container"]["view_id"]
    id: str = body["actions"][0]["selected_option"]["value"]

    """
    project = getProject(id)
    """

    view = {
        "title": {"type": "plain_text", "text": "Promote project", "emoji": True},
        "submit": {"type": "plain_text", "text": "Promote!", "emoji": True},
        "type": "modal",
        "blocks": displayPromote(id=id),
    }
    # callback promoteProject
    client.views_update(  # type: ignore
        view_id=view_id,
        view=view,
    )


@app.action("promoteSpecificProject_entry")  # type: ignore
def promoteSpecificProject_entry(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    project_id: str = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "promoteProject",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": displayPromote(id=project_id),
            "private_metadata": project_id,
        },
    )


@app.action("promoteFromHome")  # type: ignore
def promoteFromHome(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "promoteProject",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": displayPromote(id=False),
        },
    )


@app.action("updateFromHome")  # type: ignore
def updateFromHome(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "loadProject",
            "title": {"type": "plain_text", "text": "Select Project"},
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": displayEditLoad(id=False),
        },
    )


@app.action("createFromHome")  # type: ignore
def createFromHome(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    # pick a new id
    id: str = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    while id in loadProjects().keys():
        id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            # View identifier
            "callback_id": "updateData",
            "title": {"type": "plain_text", "text": "Create a pledge"},
            "submit": {"type": "plain_text", "text": "Create!"},
            "private_metadata": id,
            "blocks": constructEdit(id=id),
        },
    )


@app.action("approve")  # type: ignore
def approve(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = getProject(id)

    # Projects approved in this function should be marked as DGR ineligible
    project["dgr"] = False

    project["approved"] = True
    project["approved_at"] = int(time.time())
    writeProject(id, project, user=False)

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
                    "action_id": "promoteSpecificProject_entry",
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

    updateHome(user=user, client=client)


@app.action("approve_as_dgr")  # type: ignore
def approve_as_dgr(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = getProject(id)
    project["approved"] = True
    project["approved_at"] = int(time.time())
    project["dgr"] = True
    writeProject(id, project, user=False)

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
                    "action_id": "promoteSpecificProject_entry",
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

    updateHome(user=user, client=client)


@app.action("unapprove")  # type: ignore
def unapprove(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]

    unapproveProject(id)

    updateHome(user=user, client=client)


@app.action("delete")  # type: ignore
def delete(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]

    deleteProject(id)

    updateHome(user=user, client=client)


@app.action("projectDetails")  # type: ignore
def projectDetails(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id = body["actions"][0]["value"]
    client.views_open(  # type: ignore
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Project Details"},
            "blocks": displayProjectDetails(id=id),
        },
    )


@app.action("sendInvoices")  # type: ignore
def invoice(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = getProject(id)

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
        button = body["message"]["blocks"][-1]
        # Take out the button
        blocks: list[dict[str, Any]] = body["message"]["blocks"][:-1]
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
    outcome: str = utils.project_output.send_invoices_lib(id)
    sent: bool = True if "Error:" not in outcome[:6] else False

    # If we came from a message we can add the trigger button back in if the invoicing failed
    if body["container"]["type"] == "message":
        # If we weren't successful, add the button back at the bottom
        if not sent:
            blocks += [button]

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


@app.action("requestProjectApproval")  # type: ignore
def requestProjectApproval(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    ack()
    id: str = body["actions"][0]["value"]
    user: str = body["user"]["id"]
    project: dict[str, Any] = getProject(id)

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
    blocks += displayProject(id)
    blocks += displayApprove(id)

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

    updateHome(user=user, client=client)


### info ###


@app.options("projectSelector")  # type: ignore
def projectSelector(ack, body: dict[str, Any], client: WebClient) -> None:  # type: ignore
    if auth(user=body["user"]["id"], client=client):
        ack(options=projectOptions())
    else:
        ack(options=projectOptions(restricted=body["user"]["id"], approved=False))


@app.options("projectPreviewSelector")  # type: ignore
def projectPreviewSelector_opt(ack) -> None:  # type: ignore
    ack(options=projectOptions(approved=True))


# Update the app home
@app.event("app_home_opened")  # type: ignore
def app_home_opened(event: dict[str, Any], client: WebClient) -> None:
    updateHome(user=event["user"], client=client)


# Get TidyHQ org details
tidyhq_org: dict[str, Any] = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": config["tidyhq_token"]},
).json()

# Start listening for commands
if __name__ == "__main__":
    SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()
