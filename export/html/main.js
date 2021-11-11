/*
  JSON requires the following fields:
    title (str), desc (str), raised (float), total (float), backers (int), createdBy (str), img (str/url).
  TO ADD: link (url for proj on slack to pledge), createdByLink (slack url of person).

  The progress bars are created by setting the width attribute of an inner bar through js to the percentage raised. Alternative would be to use the HTML element meter or progress, however this is not ubiquitously supported by browsers.

  Flexbox is used for the project cards, and is responsive based on screen size. Add as many projects as needed, and they should appear nicely.
*/

// variables to modify
var jsonLink = "https://gist.githubusercontent.com/spacecadet12/fc21c7f79fc9e84784ee20bd95cbfaa9/raw/ff87b501c6f633e98ed4482347f5d5b27ac91cc2/projects.json";
var pageTitle = "Artifactory Pledges";
var pageDescription = "This is a brief description that goes at the top of the page, to describe the purpose of the page, why the pledges exist, how to donate etc. You can update this in the main.js file and can include basic html tags for links etc. Link to slack? How to donate?";

var xhttp = new XMLHttpRequest();
xhttp.responseType = 'JSON';
xhttp.onreadystatechange = function() {
    if (this.readyState == 4 && this.status == 200) {
      var data = this.response;
      // console.log(data);
      showData(data);
    }
};
xhttp.open("GET", jsonLink, true);
xhttp.send();

var mainContainer = document.getElementById("content");
document.title = pageTitle;
document.getElementById("title").innerHTML = pageTitle;
document.getElementById("pageDescription").innerHTML = pageDescription;

function showData(jsonObj) {
  var projs = JSON.parse(jsonObj);
  for (var i = 0; i < projs.length; i++) {
    // create parent div card --> flexbox child.
    var card = document.createElement('div');
    card.setAttribute('class','card');

    // create sub elements.
    var cardTitle = document.createElement('p');
    var cardLink = document.createElement('a');
    var cardDesc = document.createElement('p');
    var cardImg = document.createElement('img');

    // add classes/attributes.
    cardTitle.setAttribute('class','cardTitle');
    cardLink.setAttribute('href',"The link that will be in the json to the slack proj");
    cardDesc.setAttribute('class','cardDescription');
    cardImg.setAttribute('class','cardImage');
    cardImg.setAttribute('alt','Image representing the project.');

    // set content.
    cardLink.innerHTML = projs[i].title;
    cardDesc.innerHTML = projs[i].desc;
    cardImg.setAttribute('src',projs[i].img);

    // add elements to card element.
    cardTitle.appendChild(cardLink);
    card.appendChild(cardTitle);
    // easier to use this string than manually create all the sub elements while maintaining their hierarchy.
    var insertCode = `
    <div class="cardProgress">
      <div class="cardProgressBar">
        <div class="cardProgressBarInner" id="progressIndicator${i}"></div>
      </div>
      <p class="cardProgressText">
        <span class="moneyRaised" id="moneyRaised${i}"></span>/<span class="moneyTarget" id="moneyTarget${i}"></span> pledged | <span class="backersText" id="backersText${i}"></span> backers<br /><strong>Created by: </strong>
        <span class="createdBy" id="createdBy${i}"></span>
      </p>
    </div>
    `;
    card.innerHTML += insertCode;

    card.appendChild(cardImg);
    card.appendChild(cardDesc);

    mainContainer.appendChild(card);

    // set the content of the objects created in the html string.
    document.getElementById(`progressIndicator${i}`).style.width = (projs[i].raised / projs[i].total)*100 + "%";
    document.getElementById(`moneyRaised${i}`).innerHTML = "$" + projs[i].raised;
    document.getElementById(`moneyTarget${i}`).innerHTML = "$" + projs[i].total;
    document.getElementById(`backersText${i}`).innerHTML = projs[i].backers;
    document.getElementById(`createdBy${i}`).innerHTML = projs[i].createdBy;
  }
}
