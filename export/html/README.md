# HTML display

These files are a template for displaying JSON data from pledgebot as a webpage.

See variables at the top of main.js to modify, including URL of the JSON file and some other information.

Requires the JSON file to have the following fields:
title (str), desc (str), raised (float), total (float), backers (int), createdBy (str), img (str/url).

Fields to add: link (url for proj on slack to pledge), createdByLink (slack url of person).

The progress bars are created by setting the width attribute of an inner bar through js to the percentage raised. Alternative would be to use the HTML element meter or progress, however this is not ubiquitously supported by browsers.

 Flexbox is used for the project cards, and is responsive based on screen size. Add as many projects as needed, and they should appear nicely.
