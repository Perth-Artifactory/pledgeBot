# pledgeBot

Project pledge system for Slack

## Requirements

* [slack_bolt](https://pypi.org/project/slack-bolt/)
* Requests
* Images from [laserlemon/slack_progress_bar](https://github.com/laserlemon/slack_progress_bar)

## Configuration

* Copy `config.json.example` and `projects.json.example`. Technically `project.json` could start with just `{}`.
* Add the [progress bar emoji](./rsc/images/slack_progress_bar) to Slack.

## Usage

The primary interaction surface for the bot as a project creator is the App home. This will list:

* Projects looking for donations
* Projects awaiting approval (admin)
* Personal projects not yet approved
* Recently completed projects
* Editing tools (admin)

The expectation is that while sporadic/infrequent donors **can** use the App home they'll primarily interact with promoted projects elsewhere on Slack.

## Development

Bugs and improvements are getting documented as issues, no real todo. All future changes should be backwards compatible with existing project stores.
