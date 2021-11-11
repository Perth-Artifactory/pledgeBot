#!/usr/bin/python3

import json

def loadProjects():
    with open("../projects.json","r") as f:
        return json.load(f)

with open("page.html.template","r") as f:
    page_html = f.read()

with open("project.html.template","r") as f:
    project_html = f.read()

project_string = ""
projects = loadProjects()

for project in projects:
    # project formatting code here

    project_formatted == project_html.format()
    project_string += "\n"+project_formatted

output = page_html.format(project_string)

with open("projects.html","w") as f:
    f.write(output)
