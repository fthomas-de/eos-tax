/* The in-game character of the bots page and the window buttons beside
 * the names.
 *
 * Clicks are caught on the document: the tabs after the first are fetched
 * when opened, and their buttons do not exist yet when this runs. Every
 * answer is a message for the status line in the card header.
 */
document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const box = document.querySelector("[data-eos-ui-character]");

    if (!box) {
        return;
    }

    const result = box.querySelector("[data-eos-ui-result]");
    const select = box.querySelector("select");

    function post(url, body) {
        result.textContent = "";

        return fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": box.querySelector("[name=csrfmiddlewaretoken]").value,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: new URLSearchParams(body).toString(),
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }

                return response.json();
            })
            .then(function (data) {
                result.textContent = data.message;
            })
            .catch(function (error) {
                result.textContent = box.dataset.eosLabelError;
                console.error("eos_tax: in-game window request failed", error);
            });
    }

    select.addEventListener("change", function () {
        post(box.dataset.eosSelectUrl, {character_id: select.value});
    });

    document.addEventListener("click", function (event) {
        const button = event.target.closest("[data-eos-open-window]");

        if (!button) {
            return;
        }

        button.disabled = true;
        post(button.dataset.eosOpenWindow, {}).finally(function () {
            button.disabled = false;
        });
    });
});
