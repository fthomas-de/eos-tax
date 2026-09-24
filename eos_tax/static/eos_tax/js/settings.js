/* The recalculate control on the settings page: posts to its own endpoint
 * and swaps in whatever it renders - a log for one Corporation, or a
 * confirmation that every Corporation was queued. A plain button rather
 * than a submit, so it never depends on the rest of the configuration form
 * also being valid right now.
 */
document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const button = document.getElementById("eos-tax-recalc-run");
    const result = document.getElementById("eos-tax-recalc-result");

    if (!button || !result) {
        return;
    }

    const config = JSON.parse(
        document.getElementById("eos-tax-config").textContent
    );

    button.addEventListener("click", function () {
        const corpId = document.getElementById("eos-tax-recalc-corp").value;
        const month = document.getElementById("eos-tax-recalc-month").value;
        const year = document.getElementById("eos-tax-recalc-year").value;
        // the page's own form already carries one - a second hidden input
        // would just be another thing to keep in sync with it
        const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;

        button.disabled = true;
        result.textContent = config.loading;

        const body = new URLSearchParams({ corp_id: corpId, month: month, year: year });

        fetch(config.recalculateUrl, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrfToken,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body: body.toString(),
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(response.status);
                }

                return response.text();
            })
            .then(function (html) {
                result.innerHTML = html;
            })
            .catch(function (error) {
                result.textContent = config.error;
                console.error("eos_tax: recalculation failed", error);
            })
            .finally(function () {
                button.disabled = false;
            });
    });
});
