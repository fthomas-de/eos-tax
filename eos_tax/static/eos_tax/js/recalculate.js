/* The recalculate buttons of the bots page and GM Transactions.
 *
 * Each queues the job behind its page alone and leaves the rest to the
 * progress bar above: the reply only says whether it queued one or a run of
 * it was already waiting or going. The page is not reloaded - the bar offers
 * that once the job has finished.
 */
document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    document.querySelectorAll("[data-eos-recalculate]").forEach(function (box) {
        const button = box.querySelector("button");
        const result = box.querySelector("[data-eos-recalculate-result]");

        button.addEventListener("click", function () {
            const body = new URLSearchParams();

            if (box.dataset.eosRecalculateMonth) {
                body.set("month", box.dataset.eosRecalculateMonth);
            }

            button.disabled = true;
            result.textContent = "";

            fetch(box.dataset.eosRecalculateUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": box.querySelector("[name=csrfmiddlewaretoken]").value,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                body: body.toString(),
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(response.status);
                    }

                    return response.json();
                })
                .then(function (data) {
                    result.textContent = data.queued
                        ? box.dataset.eosLabelQueued
                        : box.dataset.eosLabelRunning;
                })
                .catch(function (error) {
                    result.textContent = box.dataset.eosLabelError;
                    console.error("eos_tax: queueing the recalculation failed", error);
                })
                .finally(function () {
                    button.disabled = false;
                    // the bar only polls while it knows of a run; this one is new
                    document.dispatchEvent(new CustomEvent("eos-tax:progress-poll"));
                });
        });
    });
});
