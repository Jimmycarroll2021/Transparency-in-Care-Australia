// Client-side search over assets/search-index.json. No external requests, no storage.
// Results are built with textContent only: no index value is ever parsed as HTML.
(function () {
  "use strict";
  var input = document.getElementById("q");
  var list = document.getElementById("results");
  var status = document.getElementById("status");
  if (!input || !list || !status) {
    return;
  }
  var index = null;
  var LIMIT = 24;
  var ABSENCE = "Absence of a record here is not evidence that a service is safe or compliant.";

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
          return { row: r, hay: norm(r.slice(1, 8).join(" ")), name: norm(r[1]) };
        });
        return index;
      });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) {
      node.className = cls;
    }
    if (text) {
      node.textContent = text;
    }
    return node;
  }

  function card(r) {
    // r: [kind, name, suburb, postcode, state, key, providerName, providerKey, url, actions]
    var isService = r[0] === "s";
    var a = el("a", "result-card");
    a.href = r[8];
    var top = el("span", "result-top");
    top.appendChild(el("span", "result-kind", isService ? "Service" : "Provider"));
    var n = Number(r[9]) || 0;
    top.appendChild(el("span", "result-count", n + (n === 1 ? " published action" : " published actions")));
    a.appendChild(top);
    a.appendChild(el("span", "result-name", r[1]));
    var meta = isService ? [[r[2], r[4], r[3]].filter(Boolean).join(" "), r[5]] : [r[5]];
    a.appendChild(el("span", "result-meta", meta.filter(Boolean).join(", ")));
    if (isService && r[6]) {
      a.appendChild(el("span", "result-provider", "Provider: " + r[6]));
    }
    return a;
  }

  function render(matches, query) {
    list.textContent = "";
    matches.slice(0, LIMIT).forEach(function (m) {
      var li = document.createElement("li");
      li.appendChild(card(m.row));
      list.appendChild(li);
    });
    if (!query) {
      status.textContent = "";
    } else if (matches.length === 0) {
      status.textContent = "No matches. " + ABSENCE;
    } else if (matches.length > LIMIT) {
      status.textContent = matches.length + " matches; showing the first " + LIMIT + ". Add more words to narrow the search.";
    } else {
      status.textContent = matches.length + (matches.length === 1 ? " match." : " matches.");
    }
  }

  function rank(m, query) {
    // Names that start with the query first, then names containing it, then other fields.
    // Within each group a provider comes before its services.
    var base = m.name.indexOf(query) === 0 ? 0 : m.name.indexOf(query) !== -1 ? 2 : 4;
    return base + (m.row[0] === "p" ? 0 : 1);
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
          matches.sort(function (a, b) {
            return rank(a, query) - rank(b, query);
          });
          render(matches, query);
        })
        .catch(function () {
          status.textContent = "Search is unavailable. The index could not be loaded.";
        });
    }, 150);
  });
})();
