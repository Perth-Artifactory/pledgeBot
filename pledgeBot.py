#!/usr/bin/python3

import json
import string
import random
from pprint import pprint
import requests
import time

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

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
def writeProject(id, data, user):
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
        app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=f'"{data["title"]}" has been created by <@{user}>. It will need to be approved before it will show up on the full list of projects or to be marked as DGR eligible. This can be completed by any member of <@{config["admin_group"]}> by clicking on my name.',
        )

    else:
        if user:
            data["last updated by"] = user
            data["last updated at"] = int(time.time())

            # Send a notice to the admin channel and add further details as a thread
            reply = app.client.chat_postMessage(
                channel=config["admin_channel"],
                text=f'"{data["title"]}" has been updated by <@{user}>.',
            )

            app.client.chat_postMessage(
                channel=config["admin_channel"],
                thread_ts=reply["ts"],
                text=f"Old:\n```{json.dumps(loadProjects()[id], indent=4, sort_keys=True)}```",
            )

            app.client.chat_postMessage(
                channel=config["admin_channel"],
                thread_ts=reply["ts"],
                text=f"New:\n```{json.dumps(data, indent=4, sort_keys=True)}```",
            )

            # Send a notice to the project creator if they're not the one updating it
            if data["created by"] != user:
                # Open a slack conversation with the creator and get the channel ID
                r = app.client.conversations_open(users=data["created by"])
                channel_id = r["channel"]["id"]

                # Notify the creator
                app.client.chat_postMessage(
                    channel=channel_id,
                    text=f'A project you created ({data["title"]}) has been updated by <@{user}>.',
                )

        projects[id] = data
        with open("projects.json", "w") as f:
            json.dump(projects, f, indent=4, sort_keys=True)


def getProject(id):
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


def validateId(id):
    allowed = set(string.ascii_letters + string.digits + "_" + "-")
    if set(id) <= allowed:
        return True
    return False


def pledge(id, amount, user, percentage=False):
    project = loadProjects()[id]
    if "pledges" not in project.keys():
        project["pledges"] = {}
    if amount == "remaining":
        current_total = 0
        for pledge in project["pledges"]:
            if pledge != user:
                current_total += int(project["pledges"][pledge])
        amount = project["total"] - current_total
    if percentage:
        amount = int(project["total"] * (amount / 100))
    project["pledges"][user] = int(amount)
    writeProject(id, project, user=False)

    # Open a slack conversation with the donor and get the channel ID
    r = app.client.conversations_open(users=user)
    channel_id = r["channel"]["id"]

    # Notify/thank the donor

    app.client.chat_postMessage(
        channel=channel_id,
        text=f'We\'ve updated your *total* pledge for "{project["title"]}" to ${amount}. Thank you for your support!\n\nOnce the project is fully funded I\'ll be in touch to arrange payment.',
    )

    # Check if the project has met its goal
    if check_if_funded(id=id):
        # Notify the admin channel
        app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has met its funding goal! For now the next step is for a backend admin to trigger invoice generation.',
        )

        # Mark when the project was funded
        project["funded at"] = int(time.time())
        writeProject(id, project, user=False)

    # Send back an updated project block

    return displayProject(id) + displaySpacer() + displayDonate(id)


def projectOptions(restricted=False, approved=False):
    projects = loadProjects()
    options = []
    for project in projects:
        # Don't present funded projects as options
        if check_if_funded(id=project):
            continue

        # If only approved projects have been requested, skip unapproved projects
        if approved:
            if not projects[project].get("approved", False):
                continue

        if restricted:
            if projects[project]["created by"] == restricted:
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


def slackIdShuffle(field, r=False):
    # This function is used when we want to disable Slack's input preservation.
    if r:
        return field.split("SHUFFLE")[0]
    return "{}SHUFFLE{}".format(
        field, "".join(random.choices(string.ascii_letters + string.digits, k=16))
    )


def checkBadCurrency(s):
    try:
        s = int(s)
    except ValueError:
        return "Donation pledges must be a number. `{}` wasn't recognised.".format(s)

    if int(s) < 1:
        return "Donation pledges must be a positive number."

    return False


def auth(client, user):
    r = app.client.usergroups_list(include_users=True)
    groups = r.data["usergroups"]
    for group in groups:
        if group["id"] == config["admin_group"]:
            authUsers = group["users"]
            if user in authUsers:
                return True
    return False


def check_if_funded(project=None, id=None):
    if id:
        project = getProject(id)

    currentp = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            currentp += int(project["pledges"][pledge])
    if currentp >= project["total"]:
        return True
    return False


def check_if_old(project=None, id=None):
    """Returns True if the project was funded more than age_out_threshold days ago"""
    if id:
        project = getProject(id)

    if "funded at" in project.keys():
        if (
            int(time.time()) - project["funded at"]
            > 86400 * config["age_out_threshold"]
        ):
            return True
        return False
    return True


#####################
# Display functions #
#####################


def constructEdit(id):
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
    # Is this a new project? If so don't show the selection box
    if project["desc"]:
        editbox = displayEditLoad(id) + displaySpacer() + editbox
    return editbox


def displayProject(id):
    project = getProject(id)
    image = "https://github.com/Perth-Artifactory/branding/blob/main/artifactory_logo/png/Artifactory_logo_MARK-HEX_ORANG.png?raw=true"  # default image
    if project["img"]:
        image = project["img"]
    title = project["title"]
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
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "{} ${}/${} | {} backers\n".format(
                    createProgressBar(currentp, project["total"]),
                    currentp,
                    project["total"],
                    backers,
                )
                + "{} \n".format(project["desc"])
                + "*Created by*: <@{}> *Last updated by*: <@{}>".format(
                    project["created by"], project["last updated by"]
                ),
            },
            "accessory": {
                "type": "image",
                "image_url": image,
                "alt_text": "Project image",
            },
        },
    ]

    return blocks


def displayApprove(id):
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
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Edit project",
                        "emoji": True,
                    },
                    "style": "danger",
                    "value": id,
                    "action_id": "editSpecificProject",
                },
            ],
        }
    ]
    return blocks


def displayDonate(id, user=None, home=False):
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
                "block_id": id,
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
                blocks[0]["elements"][0][
                    "text"
                ] += f' Thank you for your ${project["pledges"][user]} donation!'
            else:
                # Prefill their existing donation amount.
                blocks[0]["element"]["initial_value"] = str(project["pledges"][user])
                blocks += [
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "plain_text",
                                "text": "Thanks for your ${} donation! You can update your pledge using the buttons above.".format(
                                    project["pledges"][user]
                                ),
                                "emoji": True,
                            }
                        ],
                    }
                ]

    return blocks


def displayEditLoad(id):
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
    if id:
        project = getProject(id)
        initial = {
            "text": {"text": project["title"], "type": "plain_text"},
            "value": id,
        }
        box[0]["elements"][0]["initial_option"] = initial
    return box


def displaySpacer():
    return [{"type": "divider"}]


def displayHeader(s):
    return [
        {"type": "header", "text": {"type": "plain_text", "text": s, "emoji": True}}
    ]


def displayPromote(id=False):
    blocks = [
        {
            "type": "actions",
            "block_id": "promote",
            "elements": [
                {
                    "type": "conversations_select",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a public channel",
                        "emoji": True,
                    },
                    "filter": {"include": ["public"]},
                    "action_id": "conversationSelector",
                    "default_to_current_conversation": True,
                },
                {
                    "type": "external_select",
                    "action_id": "projectPreviewSelector",
                    "placeholder": {
                        "type": "plain_text",
                        "text": "Select a project to update",
                    },
                    "min_query_length": 0,
                },
            ],
        }
    ]
    if id:
        pass
        blocks = blocks + displaySpacer() + displayProject(id)
    return blocks


# this will be inaccurate if segments * 4 + 2 is not a whole number
def createProgressBar(current, total, segments=7):
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
    final_s += ":pb-{}-a:".format(s[0])
    s = s[1:]

    # Fill the middle
    while len(s) > 1:
        final_s += ":pb-{}:".format(s[:4])
        s = s[4:]

    # Add the ending cap
    final_s += ":pb-{}-z:".format(s[0])

    return final_s


def displayHomeProjects(user, client):
    projects = loadProjects()

    blocks = displayHeader("Projects seeking donations")
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
            blocks += displaySpacer()

    blocks += displayHeader("Recently funded projects")
    for project in projects:
        if check_if_funded(id=project) and not check_if_old(id=project):
            blocks += displayProject(project)
            blocks += displaySpacer()

    if auth(user=user, client=client):
        blocks += displayHeader("Projects awaiting approval")
        for project in projects:
            if not projects[project].get("approved", False):
                blocks += displayProject(project)
                blocks += displayApprove(project)
                blocks += displaySpacer()
    else:
        not_yet_approved = []
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
                            "text": f'These are projects you have created that haven\'t been approved yet. Press the "Request approval" button once your project is ready to go.',
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
                                "action_id": "requestProjectApproval",
                            },
                        ],
                    }
                ]
                blocks += displaySpacer()
    return blocks


######################
# Listener functions #
######################

# Initialise slack

app = App(token=config["SLACK_BOT_TOKEN"])

### slash commands ###


@app.command("/pledge")
def entryPoints(ack, respond, command, client, body):
    ack()
    # Did the user provide a command?
    if command["text"] != "":
        command = command["text"].split(" ")[0].lower()
    else:
        pass
        # Some help text

    if command == "create":
        # pick a new id
        id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        while id in loadProjects().keys():
            id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        client.views_open(
            # Pass a valid trigger_id within 3 seconds of receiving it
            trigger_id=body["trigger_id"],
            # View payload
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

    elif command == "update":
        client.views_open(
            # Pass a valid trigger_id within 3 seconds of receiving it
            trigger_id=body["trigger_id"],
            # View payload
            view={
                "type": "modal",
                # View identifier
                "callback_id": "loadProject",
                "title": {"type": "plain_text", "text": "Select Project"},
                "submit": {"type": "plain_text", "text": "Update!"},
                "blocks": displayEditLoad(id=False),
            },
        )

    elif command == "promote":
        client.views_open(
            # Pass a valid trigger_id within 3 seconds of receiving it
            trigger_id=body["trigger_id"],
            # View payload
            view={
                "type": "modal",
                # View identifier
                "callback_id": "promoteProject",
                "title": {"type": "plain_text", "text": "Promote a pledge"},
                "submit": {"type": "plain_text", "text": "Promote!"},
                "blocks": displayPromote(id=False),
            },
        )

    else:
        pass
        # Some help text, pointing out that the command wasn't recognised


### Actions ###


def updateHome(user, client):
    docs = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "How to create a project",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "You can either create a new project using `/pledge create` or by using the button here.\nThe most successful projects tend to include the following things:\n - A useful title\n - A description that explains what the project is and why it would benefit the space. Instead of going into the minutiae provide a slack channel or wiki url where users can find more info for themselves.\n - A pretty picture. Remember pictures are typically displayed quite small so use them as an attraction rather than a method to convey detailed information. If you opt not to include an image we'll use a placeholder :artifactory2: instead.",
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Create a project",
                    "emoji": True,
                },
                "value": "AppHome",
                "action_id": "createFromHome",
            },
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "How to update a project",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "You can either update a project using `/pledge update` or by using the button here.\n We've given you complete freedom to update the details of your project and trust you to use this power responsibly. Existing promotional messages won't be updated unless someone interacts with them (donates).",
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Update a project",
                    "emoji": True,
                },
                "value": "AppHome",
                "action_id": "updateFromHome",
            },
        },
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "How to promote a project",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "You can either update a project using `/pledge promote` or by using the buttons next to each project listed above.\n\n pledgeBot will post a promotional message in a public channel of your choosing. For channels dedicated to a particular project you could pin the promotional message as an easy way of reminding people that they can donate.\nBeyond the technical functions we suggest actively talking about your project in the most relevant channel. If you want to purchase a new 3D printer then <#CG05N75DZ> would be the best place to start.",
            },
            "accessory": {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Promote a project",
                    "emoji": True,
                },
                "value": "AppHome",
                "action_id": "promoteFromHome",
            },
        },
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Further help", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "If you want help workshopping a proposal the folks in <#CFWCKULHY> are a good choice. Alternatively reaching out to a <!subteam^SFH110QD8> committee member will put you in contact with someone that has a pretty good idea of what's going on in the space.\nMoney questions should be directed to <!subteam^S01D6D2T485> \nIf you're having trouble with the pledge system itself chat with <@UC6T4U150> or raise an issue on <https://github.com/Perth-Artifactory/pledgeBot/issues|GitHub>.",
            },
        },
    ]

    home_view = {
        "type": "home",
        "blocks": displayHomeProjects(client=client, user=user) + docs,
    }

    client.views_publish(user_id=user, view=home_view)


@app.view("updateData")
def updateData(ack, body, client):
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

    # Find our slackIdShuffle'd field
    for field in data:
        if slackIdShuffle(field, r=True) == "total":
            total_shuffled = field

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


@app.view("promoteProject")
def handle_view_events(ack, body):
    ack()
    try:
        id = body["view"]["state"]["values"]["promote"]["projectPreviewSelector"][
            "selected_option"
        ]["value"]
    except TypeError:
        id = body["view"]["private_metadata"]

    channel = body["view"]["state"]["values"]["promote"]["conversationSelector"][
        "selected_conversation"
    ]
    title = getProject(id)["title"]

    # Add promoting as a separate message so it can be removed by a Slack admin if desired. (ie when promoted as part of a larger post)
    app.client.chat_postMessage(
        channel=channel,
        text="<@{}> has promoted a project, check it out!".format(body["user"]["id"]),
    )
    app.client.chat_postMessage(
        channel=channel,
        blocks=displayProject(id) + displaySpacer() + displayDonate(id),
        text="Check out our fundraiser for: {}".format(title),
    )


@app.action("projectSelector")
def projectSelected(ack, body, respond, client):
    ack()
    id = body["view"]["state"]["values"]["projectDropdown"]["projectSelector"][
        "selected_option"
    ]["value"]
    # id = body["actions"][0]["selected_option"]["value"]
    view_id = body["container"]["view_id"]
    project = getProject(id)
    client.views_update(
        # Pass a valid trigger_id within 3 seconds of receiving it
        view_id=view_id,
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "updateData",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },  # project["title"]
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": constructEdit(id),
            "private_metadata": id,
        },
    )


@app.action("editSpecificProject")
def projectSelected(ack, body, respond, client):
    ack()

    id = body["actions"][0]["value"]
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
        trigger_id=body["trigger_id"],
        # View payload
        view={
            "type": "modal",
            "callback_id": "updateData",
            "title": {
                "type": "plain_text",
                "text": "Update Project",
            },
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": constructEdit(id),
            "private_metadata": id,
        },
    )


# Donate buttons with inline update


@app.action("donate10")
def handle_some_action(ack, body, respond):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks=pledge(id, 10, user, percentage=True))


@app.action("donate20")
def handle_some_action(ack, body, respond, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks=pledge(id, 20, user, percentage=True))


@app.action("donateRest")
def handle_some_action(ack, body, respond, say, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks=pledge(id, "remaining", user))


@app.action("donateAmount")
def handle_some_action(ack, body, respond, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["block_id"]
    amount = body["actions"][0]["value"]
    if checkBadCurrency(amount):
        respond(
            text=checkBadCurrency(amount),
            replace_original=False,
            response_type="ephemeral",
        )
    else:
        respond(blocks=pledge(id, amount, user))


# Donate buttons with home update


@app.action("donate10_home")
def handle_some_action(ack, body, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    pledge(id, 10, user, percentage=True)
    updateHome(user=user, client=client)


@app.action("donate20_home")
def handle_some_action(ack, body, event, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    event = {"user": user}
    pledge(id, 20, user, percentage=True)
    updateHome(user=user, client=client)


@app.action("donateRest_home")
def handle_some_action(ack, body, event, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    event = {"user": user}
    pledge(id, "remaining", user)
    updateHome(user=user, client=client)


@app.action("donateAmount_home")
def handle_some_action(ack, body, event, client, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["block_id"]
    amount = body["actions"][0]["value"]
    event = {"user": user}
    if checkBadCurrency(amount):
        say(text=checkBadCurrency(amount), channel=user)
    else:
        pledge(id, amount, user)
        updateHome(user=user, client=client)


@app.action("conversationSelector")
def handle_some_action(ack, body, logger):
    ack()
    # we actually don't want to do anything yet


@app.action("projectPreviewSelector")
def handle_some_action(ack, body, respond, client):
    ack()
    view_id = body["container"]["view_id"]
    id = body["actions"][0]["selected_option"]["value"]

    """
    project = getProject(id)
    """
    client.views_update(
        # Pass a valid trigger_id within 3 seconds of receiving it
        view_id=view_id,
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "promoteProject",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": displayPromote(id),
            "private_metadata": id,
        },
    )


@app.action("promoteSpecificProject_entry")
def handle_some_action(ack, body, client):
    ack()
    project_id = body["actions"][0]["value"]
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
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


@app.action("promoteFromHome")
def handle_some_action(ack, body, client):
    ack()
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
        trigger_id=body["trigger_id"],
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "promoteProject",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": displayPromote(id=False),
        },
    )


@app.action("updateFromHome")
def handle_some_action(ack, body, client):
    ack()
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
        trigger_id=body["trigger_id"],
        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "loadProject",
            "title": {"type": "plain_text", "text": "Select Project"},
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": displayEditLoad(id=False),
        },
    )


@app.action("createFromHome")
def handle_some_action(ack, body, client):
    ack()
    # pick a new id
    id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    while id in loadProjects().keys():
        id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
    client.views_open(
        # Pass a valid trigger_id within 3 seconds of receiving it
        trigger_id=body["trigger_id"],
        # View payload
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


@app.action("approve")
def handle_some_action(ack, body, client):
    ack()
    id = body["actions"][0]["value"]
    user = body["user"]["id"]
    project = getProject(id)
    project["approved"] = True
    project["approved_at"] = int(time.time())
    writeProject(id, project, user=None)

    # Open a slack conversation with the creator and get the channel ID
    r = app.client.conversations_open(users=project["created by"])
    channel_id = r["channel"]["id"]

    # Notify the creator
    app.client.chat_postMessage(
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
        app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has been approved by <@{user}>.',
        )

    # Coming from a message, which means we can just update that message
    elif body["container"]["type"] == "message":
        # Take out the approval buttons
        blocks = body["message"]["blocks"][:-1]
        blocks += [
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"<@{user}> approved this project"}
                ],
            }
        ]

        app.client.chat_update(
            channel=body["container"]["channel_id"],
            ts=body["container"]["message_ts"],
            blocks=blocks,
            text=f"Project approved by <@{user}>",
            as_user=True,
        )

    updateHome(user=user, client=client)


@app.action("approve_as_dgr")
def handle_some_action(ack, body, client):
    ack()
    id = body["actions"][0]["value"]
    user = body["user"]["id"]
    project = getProject(id)
    project["approved"] = True
    project["approved_at"] = int(time.time())
    project["dgr"] = True
    writeProject(id, project, user=None)

    # Open a slack conversation with the creator and get the channel ID
    r = app.client.conversations_open(users=project["created by"])
    channel_id = r["channel"]["id"]

    # Notify the creator
    app.client.chat_postMessage(
        channel=channel_id,
        text=f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice. Additionally, we have marked this project as qualified for <{config["tax_info"]}|tax deductible donations>.',
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f'Your project "{project["title"]}" has been approved! You can now promote it to a channel of your choice.\nAdditionally, we have marked this project as qualified for <{config["tax_info"]}|tax deductible donations>.',
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
        app.client.chat_postMessage(
            channel=config["admin_channel"],
            text=f'"{project["title"]}" has been marked as tax deductible and approved by <@{user}>.',
        )

    # Coming from a message, which means we can just update that message
    elif body["container"]["type"] == "message":
        # Take out the approval buttons
        blocks = body["message"]["blocks"][:-1]
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

        app.client.chat_update(
            channel=body["container"]["channel_id"],
            ts=body["container"]["message_ts"],
            blocks=blocks,
            text=f"Project approved by <@{user}>",
            as_user=True,
        )

    updateHome(user=user, client=client)


@app.action("requestProjectApproval")
def handle_some_action(ack, body, client):
    ack()
    id = body["actions"][0]["value"]
    user = body["user"]["id"]
    project = getProject(id)

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

    app.client.chat_postMessage(
        channel=config["admin_channel"],
        text=f'<@{user}> has requested approval for "{project["title"]}".',
        blocks=blocks,
    )

    # Open a slack conversation with the creator and get the channel ID
    r = app.client.conversations_open(users=project["created by"])
    channel_id = r["channel"]["id"]

    # Notify the creator
    app.client.chat_postMessage(
        channel=channel_id,
        text=f'Your project "{project["title"]}" has been submitted for approval.',
    )

    updateHome(user=user, client=client)


### info ###


@app.options("projectSelector")
def sendOptions(ack, body, client):
    if auth(user=body["user"]["id"], client=client):
        ack(options=projectOptions())
    else:
        ack(options=projectOptions(restricted=body["user"]["id"]))


@app.options("projectPreviewSelector")
def handle_some_options(ack, body):
    ack(options=projectOptions(approved=True))


# Update the app home
@app.event("app_home_opened")
def app_home_opened(event, client, logger):
    updateHome(user=event["user"], client=client)


# Get TidyHQ org details
r = requests.get(
    "https://api.tidyhq.com/v1/organization",
    params={"access_token": config["tidyhq_token"]},
)
tidyhq_org = r.json()

# Start listening for commands
if __name__ == "__main__":
    SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()
