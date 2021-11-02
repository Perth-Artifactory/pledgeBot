# pledgeBot

Project pledge system for Slack

## Requirements

* [slack_bolt](https://pypi.org/project/slack-bolt/)

## Configuration

## Slash commands

### Create a pledge

`/pledge create <id>`

Create a new pledge. `id` must be comprised of alphanumeric characters as well as `- and _`

### Update pledge details

`/pledge update <id> <title|description|total|image> data`

Update the details of a pledge. `id` should be previously created with `/pledge create`

* `title` - The name of the project
* `description` - A description of what the project is and why it would be helpful
* `total` - The total amount of money required to fund the project. This is generally optional but is required for some features (pledge completion and % contributions)
* `image` - A promotional image of the project. Remember that this will typicall be displayed quite small so text etc.

### Promote a pledge

`/pledge promote <id> <channel>`

Send a summary of a specific pledge to a channel

### Contribute to a pledge

`/pledge donate <id> <amount>`

Pledge to contribute $`<amount>` to a pledge

## App home

TODO
