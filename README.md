# pledgeBot

Project pledge system for Slack

## Requirements

* [slack_bolt](https://pypi.org/project/slack-bolt/)
* Images from https://github.com/laserlemon/slack_progress_bar

## Configuration

* Copy `config.json.example` and `projects.json.example`. Technically `project.json` could start with just `{}`.
* Add the [progress bar emoji](./images/slack_progress_bar) to Slack.

## Usage

### Slash commands

All commands are now contained within `/pledge`

* `/pledge create` - Generate a random ID and populate an edit modal. This hides the project selection dropdown.
* `/pledge update` - Populate an edit modal. Because Slack tries to preserve user input on modal updates we use `slackIdShuffle` to add junk data to the end of input fields.
* `/pledge promote` - Opens a modal that allows you to select a project and a channel. The bot can post in any public channel without membership (as opposed to private channels). The conversation dropdown is thus restricted to public channels.

### App home

Populated with a list of all projects and some help dialogue. The page is updated when you visit the tab or press a donate button. This also includes the only way for people to track which projects they've pledged to. Because of Slacks aforementioned input preservation the donate custom amount field doesn't update to a new amount in some conditions.

## Development

Bugs and improvements are getting documented as issues, no real todo. All future changes should be backwards compatible with existing project stores.
