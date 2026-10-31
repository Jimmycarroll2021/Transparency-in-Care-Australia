// Client-side search over assets/search-index.json. No external requests, no storage.
(function () {
  "use strict";
  var input = document.getElementById("q");
  var list = document.getElementById("results");
  var status = document.getElementById("status");
  if (!input || !list || !status) {
    return;
  }
  var index = null;
  var LIMIT = 50;

  function norm(text) {
    return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }

  function load() {
    if (index !== null) {
      return Promise.resolve(index);
    }
    return fetch("assets/search-index.json", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("index " + r.status);
        }
        return r.json();
      })
      .then(function (rows) {
        index = rows.map(function (r) {
          return { row: r, hay: norm(r.slice(1, 8).join(" ")) };
        });
        return index;
      });
  }

  function describe(r) {
    // r: [kind, name, suburb, postcode, state, key, providerName, providerKey, url]
    if (r[0] === "s") {
      var place = [r[2], r[4], r[3]].filter(Boolean).join(" ");
      var text = r[1] + (place ? ", " + place : "") + " (" + r[5] + ")";
      if (r[6]) {
        text += ". Provider: " + r[6];
      }
      return "Service: " + text;
    }
    return "Provider: " + r[1] + " (" + r[5] + ")";
  }

  function render(matches, query) {
    list.textContent = "";
    matches.slice(0, LIMIT).forEach(function (m) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = m.row[8];
      a.textContent = describe(m.row);
      li.appendChild(a);
      list.appendChild(li);
    });
    if (!query) {
      status.textContent = "";
    } else if (matches.length === 0) {
      status.textContent = "No matches. Absence of a record here is not evidence that a service is safe or compliant.";
    } else if (matches.length > LIMIT) {
      status.textContent = matches.length + " matches; showing the first " + LIMIT + ". Add more words to narrow the search.";
    } else {
      status.textContent = matches.length + (matches.length === 1 ? " match." : " matches.");
    }
  }

  var timer = null;
  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var query = norm(input.value);
      if (query.length < 2) {
        render([], "");
        return;
      }
      var terms = query.split(" ");
      load()
        .then(function (rows) {
          var matches = rows.filter(function (m) {
            return terms.every(function (t) {
              return m.hay.indexOf(t) !== -1;
            });
          });
          render(matches, query);
        })
        .catch(function () {
          status.textContent = "Search is unavailable. The index could not be loaded.";
        });
    }, 150);
  });
})();
