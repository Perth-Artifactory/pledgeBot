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

# Update project, data should be an entire project initially pulled with getProject
def writeProject(id, data, user):
    projects = loadProjects()
    if id not in projects.keys():
        # TODO show old data somewhere in slack
        data["created by"] = user
        data["last updated by"] = user
        projects[id] = data
        with open("projects.json","w") as f:
            json.dump(projects, f, indent=4, sort_keys=True)
    else:
        if user:
            data["last updated by"] = user
        projects[id] = data
        with open("projects.json","w") as f:
            json.dump(projects, f, indent=4, sort_keys=True)

def getProject(id):
    projects = loadProjects()
    if id in projects.keys():
        return projects[id]
    else:
        return {"title":"Your new project","desc":"","img":None,"total":0}

def validateId(id):
    allowed = set(string.ascii_letters + string.digits + '_' + '-')
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
                current_total += project["pledges"][pledge]
        amount = project["total"] - current_total
    if percentage:
        amount = int(project["total"] * (amount/100))
    project["pledges"][user] = amount
    writeProject(id,project,user=False)
    return displayProject(id)+displaySpacer()+displayDonate(id)

def projectOptions():
    projects = loadProjects()
    options = []
    for project in projects:
        options.append({
                      "text": {
                        "type": "plain_text",
                        "text": projects[project]["title"]
                      },
                      "value": project
                    })
    return options

def slackIdShuffle(field,r=False):
    # This function is used when we want to disable Slack's input preservation.
    if r:
        return field.split("SHUFFLE")[0]
    return "{}SHUFFLE{}".format(field,''.join(random.choices(string.ascii_letters + string.digits, k=16)))

def checkBadCurrency(s):
    try:
        s = int(s)
    except ValueError:
        return "Donation pledges must be a number. `{}` wasn't recognised.".format(s)

    if int(s) < 1:
        return "Donation pledges must be a positive number."

    return False

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
				"max_length": 64
			},
			"label": {
				"type": "plain_text",
				"text": "Project Title",
				"emoji": True
			},
			"hint": {
				"type": "plain_text",
				"text": "The name of the project.",
				"emoji": True
			}
		},
		{
			"type": "input",
            "block_id": slackIdShuffle("total"),
			"element": {
				"type": "plain_text_input",
				"action_id": "plain_text_input-action",
				"initial_value": str(project["total"])
			},
			"label": {
				"type": "plain_text",
				"text": "Total cost",
				"emoji": True
			},
			"hint": {
				"type": "plain_text",
				"text": "The estimated total cost of the project.",
				"emoji": True
			}
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
				"max_length": 1000
			},
			"label": {
				"type": "plain_text",
				"text": "Description",
				"emoji": True
			},
			"hint": {
				"type": "plain_text",
				"text": "A description of what the project is and why it would be helpful to the space. This is where you can really sell your project.",
				"emoji": True
			}
		},
		{
			"type": "input",
            "block_id": slackIdShuffle("img"),
			"optional": True,
			"element": {
				"type": "plain_text_input",
				"action_id": "plain_text_input-action",
				"initial_value": project["img"]
			},
			"label": {
				"type": "plain_text",
				"text": "Image",
				"emoji": True
			},
			"hint": {
				"type": "plain_text",
				"text": "[Optional] A URL to a promotional image for your app.",
				"emoji": True
			}
		}
	]
    # Is this a new project? If so don't show the selection box
    if project["desc"]:
        editbox = displayEditLoad(id)+displaySpacer()+editbox
    return editbox

def displayProject(id):
    project = getProject(id)
    image = "https://github.com/Perth-Artifactory/branding/blob/main/artifactory_logo/png/Artifactory_logo_MARK-HEX_ORANG.png?raw=true" #default image
    if project["img"]:
        image = project["img"]
    title = project["title"]
    currentp = 0
    backers = 0
    if "pledges" in project.keys():
        for pledge in project["pledges"]:
            backers += 1
            currentp += int(project["pledges"][pledge])
    blocks = [{
			"type": "header",
			"text": {
				"type": "plain_text",
				"text": format(project["title"]),
				"emoji": True
			}
		},
        {
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "{} ${}/${} | {} backers\n".format(createProgressBar(currentp, project["total"]), currentp, project["total"], backers) + \
                        "{} \n".format(project["desc"]) + \
                        "*Created by*: <@{}> *Last updated by*: <@{}>".format(project["created by"], project["last updated by"])
			},
			"accessory": {
				"type": "image",
				"image_url": image,
				"alt_text": "Project image"
			}
		}]
    return blocks

def displayDonate(id,user=None,home=False):
    homeadd = ""
    if home:
        homeadd = "_home"
    blocks = [
		{
			"dispatch_action": True,
            "block_id": id,
			"type": "input",
			"element": {
				"type": "plain_text_input",
				"action_id": "donateAmount" + homeadd
			},
			"label": {
				"type": "plain_text",
				"text": "Donate specific amount",
				"emoji": True
			}
		},
		{
			"type": "actions",
			"elements": [
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Donate 10%",
						"emoji": True
					},
					"value": id,
					"action_id": "donate10" + homeadd
				},
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Donate 20%",
						"emoji": True
					},
					"value": id,
					"action_id": "donate20" + homeadd
				},
				{
					"type": "button",
					"text": {
						"type": "plain_text",
						"text": "Donate the rest",
						"emoji": True
					},
					"value": id,
					"action_id": "donateRest" + homeadd
				}
			]
		}
	]

    project = getProject(id)
    # This should really only be used in the App Home since it provides personalised results

    # Has the project received pledges?
    if "pledges" in project.keys():

        # Check if the user has already donated to this project
        if user in project["pledges"]:
            # Prefill their existing donation amount.
            blocks[0]["element"]["initial_value"] = str(project["pledges"][user])
            blocks += [{
			"type": "context",
			"elements": [
				{
					"type": "plain_text",
					"text": "Thanks for your ${} donation! You can update your pledge using the buttons above.".format(project["pledges"][user]),
					"emoji": True
				}
			]
		}]

    return blocks

def displayEditLoad(id):
    box = [{
    	"type": "actions",
        "block_id": "projectDropdown",
    	"elements": [{
    			"type": "external_select",
    			"action_id": "projectSelector",
    			"placeholder": {
    				"type": "plain_text",
    				"text": "Select a project to update"
    			},
    			"min_query_length": 0
    		}
    	]
    }]
    if id:
        project = getProject(id)
        initial = {'text': {'text': project["title"], 'type': 'plain_text'}, 'value': id}
        box[0]["elements"][0]["initial_option"] = initial
    return box

def displaySpacer():
    return [{"type": "divider"}]

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
						"emoji": True
					},
                    "filter": {"include": ["public"]
					},
					"action_id": "conversationSelector",
                    "default_to_current_conversation": True
				},
				{
					"type": "external_select",
					"action_id": "projectPreviewSelector",
					"placeholder": {
						"type": "plain_text",
						"text": "Select a project to update"
					},
					"min_query_length": 0
				},
			]
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
    s = "g"*filled + "w"*(segments-filled)
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

def displayHomeProjects(user):
    projects = loadProjects()
    blocks = []
    for project in projects:
        blocks += displayProject(project)
        blocks += displayDonate(project,user=user,home=True)
        #blocks += displayPromoteButton()
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
        id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        while id in loadProjects().keys():
            id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
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
                "blocks": constructEdit(id=id)}
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
                "title": {"type": "plain_text", "text": "Update: "},
                "submit": {"type": "plain_text", "text": "Update!"},
                "blocks": displayEditLoad(id=False)}
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
                "blocks": displayPromote(id=False)}
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
				"emoji": True
			}
		},
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "You can either create a new project using `/pledge create` or by using the button here.\nThe most successful projects tend to include the following things:\n - A useful title\n - A description that explains what the project is and why it would benefit the space. Instead of going into the minutiae provide a slack channel or wiki url where users can find more info for themselves.\n - A pretty picture. Remember pictures are typically displayed quite small so use them as an attraction rather than a method to convey detailed information. If you opt not to include an image we'll use a placeholder :artifactory2: instead."
			},
			"accessory": {
				"type": "button",
				"text": {
					"type": "plain_text",
					"text": "Create a project",
					"emoji": True
				},
				"value": "AppHome",
				"action_id": "createFromHome"
			}
		},
		{
			"type": "header",
			"text": {
				"type": "plain_text",
				"text": "How to update a project",
				"emoji": True
			}
		},
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "You can either update a project using `/pledge update` or by using the button here.\n We've given you complete freedom to update the details of your project and trust you to use this power responsibly. Existing promotional messages won't be updated unless someone interacts with them (donates)."
			},
			"accessory": {
				"type": "button",
				"text": {
					"type": "plain_text",
					"text": "Update a project",
					"emoji": True
				},
				"value": "AppHome",
				"action_id": "updateFromHome"
			}
		},
		{
			"type": "header",
			"text": {
				"type": "plain_text",
				"text": "How to promote a project",
				"emoji": True
			}
		},
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "You can either update a project using `/pledge promote` or by using the buttons next to each project listed above.\n\n pledgeBot will post a promotional message in a public channel of your choosing. For channels dedicated to a particular project you could pin the promotional message as an easy way of reminding people that they can donate.\nBeyond the technical functions we suggest actively talking about your project in the most relevant channel. If you want to purchase a new 3D printer then <#CG05N75DZ> would be the best place to start."
			},
			"accessory": {
				"type": "button",
				"text": {
					"type": "plain_text",
					"text": "Promote a project",
					"emoji": True
				},
				"value": "AppHome",
				"action_id": "promoteFromHome"
			}
		},
		{
			"type": "header",
			"text": {
				"type": "plain_text",
				"text": "Further help",
				"emoji": True
			}
		},
		{
			"type": "section",
			"text": {
				"type": "mrkdwn",
				"text": "If you want help workshopping a proposal the folks in <#CFWCKULHY> are a good choice. Alternatively reaching out to a <!subteam^SFH110QD8> committee member will put you in contact with someone that has a pretty good idea of what's going on in the space.\nMoney questions should be directed to <!subteam^S01D6D2T485> \nIf you're having trouble with the pledge system itself chat with <@UC6T4U150> or raise an issue on <https://github.com/Perth-Artifactory/pledgeBot/issues|GitHub>."
			}
		}]

    client.views_publish(
        user_id=user,
        view={
            # Home tabs must be enabled in your app configuration page under "App Home"
            # and your app must be subscribed to the app_home_opened event
            "type": "home",
            "blocks": [
                		{
            			"type": "section",
            			"text": {
            				"type": "mrkdwn",
            				"text": "Everyone has different ideas about what the space needs. These are some of the projects/proposals currently seeking donations."
            			}
            		}
            ] + displaySpacer() + displayHomeProjects(user=user) + docs,
        },
    )

@app.view("updateData")
def updateData(ack, body, client):
    data = body["view"]["state"]["values"]
    if "private_metadata" in body["view"].keys():
        id = body["view"]["private_metadata"]
    else:
        id = body["view"]["state"]["values"]["projectDropdown"]["projectSelector"]["selected_option"]["value"] # Gotta be an easier way

    user = body["user"]["id"]
    # Validation
    errors = {}

    # Find our slackIdShuffle'd field
    for field in data:
        if slackIdShuffle(field,r=True) == "total":
            total_shuffled = field

    # Is cost a number


    total = data[total_shuffled]["plain_text_input-action"]["value"].replace("$","")
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
        v_clean = slackIdShuffle(v,r=True)
        if v_clean == "total":
            project[v_clean] = total
        else:
            if "plain_text_input-action" in data[v].keys():
                project[v_clean] = data[v]["plain_text_input-action"]["value"]
    writeProject(id,project,user)
    updateHome(user=user, client=client)

@app.view("promoteProject")
def handle_view_events(ack, body, logger):
    ack()
    id = body["view"]["state"]["values"]["promote"]["projectPreviewSelector"]["selected_option"]["value"]
    channel = body["view"]["state"]["values"]["promote"]["conversationSelector"]["selected_conversation"]
    title = getProject(id)["title"]
    print("sending {} ({}) to {}".format(title,id,channel))
    #respond(blocks=displayProject(id)+displaySpacer()+displayDonate(id),response_type="in_channel")
    app.client.chat_postMessage(channel=channel,
                                blocks=displayProject(id)+displaySpacer()+displayDonate(id),
                                text="Check out our fundraiser for: {}".format(title))

@app.action("projectSelector")
def projectSelected(ack, body, respond, client):
    ack()
    id = body["view"]["state"]["values"]["projectDropdown"]["projectSelector"]["selected_option"]["value"]
    #id = body["actions"][0]["selected_option"]["value"]
    view_id = body["container"]["view_id"]
    project = getProject(id)
    client.views_update(
        # Pass a valid trigger_id within 3 seconds of receiving it
        view_id = view_id,

        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "updateData",
            "title": {"type": "plain_text", "text": "Update: {}".format(id)}, # project["title"]
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": constructEdit(id),
            "private_metadata": id}
    )

# Donate buttons with inline update

@app.action("donate10")
def handle_some_action(ack, body):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks = pledge(id, 10, user, percentage=True))

@app.action("donate20")
def handle_some_action(ack, body, respond, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks = pledge(id, 20, user, percentage=True))

@app.action("donateRest")
def handle_some_action(ack, body, respond, say, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    respond(blocks = pledge(id, "remaining", user))

@app.action("donateAmount")
def handle_some_action(ack, body, respond, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["block_id"]
    amount = body["actions"][0]["value"]
    if checkBadCurrency(amount):
        respond(text=checkBadCurrency(amount), replace_original=False, response_type="ephemeral")
    else:
        respond(blocks = pledge(id, amount, user))

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
    event = {"user":user}
    pledge(id, 20, user, percentage=True)
    updateHome(user=user, client=client)

@app.action("donateRest_home")
def handle_some_action(ack, body, event, client):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["value"]
    event = {"user":user}
    pledge(id, "remaining", user)
    updateHome(user=user, client=client)

@app.action("donateAmount_home")
def handle_some_action(ack, body, event, client, say):
    ack()
    user = body["user"]["id"]
    id = body["actions"][0]["block_id"]
    amount = body["actions"][0]["value"]
    event = {"user":user}
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
        view_id = view_id,

        # View payload
        view={
            "type": "modal",
            # View identifier
            "callback_id": "promoteProject",
            "title": {"type": "plain_text", "text": "Promote a pledge"},
            "submit": {"type": "plain_text", "text": "Promote!"},
            "blocks": displayPromote(id),
            "private_metadata": id}
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
            "blocks": displayPromote(id=False)}
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
            "title": {"type": "plain_text", "text": "Update: "},
            "submit": {"type": "plain_text", "text": "Update!"},
            "blocks": displayEditLoad(id=False)}
    )

@app.action("createFromHome")
def handle_some_action(ack, body, client):
    ack()
    # pick a new id
    id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
    while id in loadProjects().keys():
        id = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
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
            "blocks": constructEdit(id=id)}
    )


### info ###

@app.options("projectSelector")
def sendOptions(ack):
    ack(options=projectOptions())

@app.options("projectPreviewSelector")
def handle_some_options(ack):
    ack(options=projectOptions())

# Update the app home
@app.event("app_home_opened")
def app_home_opened(event, client, logger):
    updateHome(user=event["user"], client=client)

# Start listening for commands
if __name__ == "__main__":
    SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()
