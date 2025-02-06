import json
from pprint import pprint
from datetime import datetime, timezone
from slack_bolt import App
import csv

# Load projects.json

with open("projects.json", "r") as f:
    projects = json.load(f)

# Load config

with open("config.json", "r") as f:
    config = json.load(f)

# Set start and end times
start_from = int(datetime(2023, 7, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
end_at = int(datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc).timestamp())

changes = "all"
# changes = "+1"
if changes == None:
    pass
elif changes == "all":
    start_from = 1
    end_at = 99999999999
elif changes[0] == "+":
    # One year in epoch is 31556952ish
    shift = int(changes[1:])
    start_from += shift * 31556952
    end_at += shift * 31556952
elif changes[0] == "-":
    shift = int(changes[1:])
    start_from -= shift * 31556952
    end_at -= shift * 31556952

# Set up variables
total_raised = 0
total_projects = 0
leaderboard = {}
creator_leaderboard = {}
table = [["Title", "Total", "Description", "# Donors"]]

for project_id in projects:
    project = projects[project_id]

    timeline = ["created at", "approved_at", "funded at"]

    # Check if project has times set

    latest = None

    for k in timeline:
        if k in project.keys():
            latest = project[k]

    if latest == None:
        print(f"Checking project: {project['title']}")
        print("Project has no times set")
        continue

    # Check if the latest time is before 2000
    if latest < 946684800:
        print(f"Checking project: {project['title']}")
        print("Project has times set before 2000")
        continue

    formatted_time = datetime.fromtimestamp(latest).strftime("%Y-%m-%d")

    # Confirm the project is within our timeframe
    if start_from <= latest <= end_at:
        print(f"Checking project: {project['title']}")
        print("Project is within timeframe")
    else:
        continue

    ### Project processing starts from here

    total_projects += 1
    total_raised += project["total"]
    table.append(
        [
            project["title"],
            project["total"],
            project["desc"],
            str(len(project["pledges"])),
        ]
    )

    # Process donors

    for donor in project["pledges"]:
        if donor not in leaderboard.keys():
            leaderboard[donor] = 0
        leaderboard[donor] += project["pledges"][donor]

    # Process creator
    if project["created by"] not in creator_leaderboard.keys():
        creator_leaderboard[project["created by"]] = {
            "projects": 0,
            "raised": 0,
            "pledged%": [],
        }
    creator_leaderboard[project["created by"]]["projects"] += 1
    creator_leaderboard[project["created by"]]["raised"] += project["total"]
    # calculate pledged percentage
    creator_percentage = (
        project["pledges"].get(project["created by"], 1) / project["total"]
    )
    creator_leaderboard[project["created by"]]["pledged%"].append(creator_percentage)


# Connect to Slack for ID lookup
app = App(token=config["SLACK_BOT_TOKEN"])

# Get a list of all users
response = app.client.users_list()
users = response["members"]
slack_db = {}
for slack_user in users:
    slack_db[slack_user["id"]] = slack_user.get("real_name", slack_user.get("name"))

# Print info

print(f"Total raised: {total_raised}")
print(f"Total projects: {total_projects}")

# Sort the leaderboard
sorted_leaderboard = dict(
    sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)
)

print(f"Total donors: {len(sorted_leaderboard)}")
print("Leaderboard:")
for donor in sorted_leaderboard:
    donor_name = slack_db.get(donor, donor)
    print(f"{donor_name}: ${sorted_leaderboard[donor]}")

print(f"Total creators: {len(creator_leaderboard)}")
print("Creator Leaderboard:")

# Sort the creator leaderboard by amount raised
creator_leaderboard = dict(
    sorted(
        creator_leaderboard.items(), key=lambda item: item[1]["raised"], reverse=True
    )
)

for creator in creator_leaderboard:
    creator_name = slack_db.get(creator, creator)
    print(
        f"{creator_name}: {creator_leaderboard[creator]['projects']} projects, ${creator_leaderboard[creator]['raised']} raised"
    )
    print("Pledged percentages: ", end="")
    average = sum(creator_leaderboard[creator]["pledged%"]) / len(
        creator_leaderboard[creator]["pledged%"]
    )
    for percentage in creator_leaderboard[creator]["pledged%"]:
        print(f"{percentage:.2%}, ", end="")

    print(f"Average: {average:.2%}")
    print(" ")


# Export table to csv

# Write data to a CSV file
with open("report.csv", "w", newline="") as file:
    writer = csv.writer(file, quotechar='"', quoting=csv.QUOTE_ALL)
    writer.writerows(table)

print("Report for individual projects sent to report.csv")
