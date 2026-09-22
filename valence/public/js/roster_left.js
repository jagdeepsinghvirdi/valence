(() => {
    const BUTTON_ID = "valence-mark-left-button";
    const PANEL_ID = "valence-mark-left-panel";
    const INSERT_SHIFT_METHOD = "valence.valence.override.whitelisted_method.roster.insert_shift";

    const state = {
        employee: "",
        employeeLabel: "",
        company: "",
        date: new Date().toISOString().slice(0, 10),
        acknowledged: false,
        busy: false,
    };

    const call = async (method, args) => {
        const response = await fetch(`/api/method/${method}`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Frappe-CSRF-Token": window.csrf_token || "",
            },
            body: JSON.stringify(args || {}),
        });

        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            const messages = payload._server_messages ? JSON.parse(payload._server_messages) : [];
            const first = messages.length ? JSON.parse(messages[0]).message : payload.exception;
            throw new Error(first || payload.exc_type || "Request failed");
        }

        return payload.message;
    };

    const searchEmployees = (term) =>
        call("frappe.client.get_list", {
            doctype: "Employee",
            filters: { status: "Active" },
            or_filters: term
                ? [
                      ["employee_name", "like", `%${term}%`],
                      ["name", "like", `%${term}%`],
                  ]
                : undefined,
            fields: ["name", "employee_name", "company"],
            limit_page_length: 20,
            order_by: "employee_name asc",
        });

    const styles = `
        #${BUTTON_ID} {
            display: inline-flex;
            align-items: center;
            height: 28px;
            padding: 0 12px;
            margin-right: 8px;
            border: 1px solid #e11d48;
            border-radius: 8px;
            background: #fff;
            color: #e11d48;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
        }
        #${BUTTON_ID}:hover { background: #fff1f2; }
        #${BUTTON_ID}.valence-floating {
            position: fixed;
            right: 24px;
            bottom: 24px;
            height: 36px;
            margin: 0;
            box-shadow: 0 6px 16px rgba(0,0,0,0.12);
            z-index: 60;
        }
        #${PANEL_ID} {
            position: fixed;
            inset: 0;
            background: rgba(17, 24, 39, 0.45);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
        }
        #${PANEL_ID} .valence-card {
            width: 420px;
            max-width: calc(100vw - 32px);
            background: #fff;
            border-radius: 12px;
            padding: 20px;
            font-family: inherit;
            color: #1f2937;
        }
        #${PANEL_ID} h3 { margin: 0 0 16px; font-size: 16px; font-weight: 600; }
        #${PANEL_ID} label { display: block; font-size: 12px; color: #6b7280; margin-bottom: 4px; }
        #${PANEL_ID} input, #${PANEL_ID} select {
            width: 100%;
            height: 32px;
            padding: 0 8px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 13px;
            background: #fff;
            color: #1f2937;
            box-sizing: border-box;
        }
        #${PANEL_ID} select { height: auto; padding: 4px; }
        #${PANEL_ID} .valence-field { margin-bottom: 14px; }
        #${PANEL_ID} .valence-warning {
            border: 1px solid #fecdd3;
            background: #fff1f2;
            color: #be123c;
            border-radius: 8px;
            padding: 12px;
            font-size: 13px;
            margin-bottom: 14px;
        }
        #${PANEL_ID} .valence-warning label {
            color: #be123c;
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 10px 0 0;
            font-size: 13px;
        }
        #${PANEL_ID} .valence-warning input { width: auto; height: auto; }
        #${PANEL_ID} .valence-actions { display: flex; justify-content: flex-end; gap: 8px; }
        #${PANEL_ID} button {
            height: 32px;
            padding: 0 14px;
            border-radius: 8px;
            font-size: 13px;
            cursor: pointer;
            border: 1px solid #d1d5db;
            background: #fff;
        }
        #${PANEL_ID} button.valence-primary {
            background: #e11d48;
            border-color: #e11d48;
            color: #fff;
        }
        #${PANEL_ID} button.valence-primary:disabled {
            background: #fca5b5;
            border-color: #fca5b5;
            cursor: not-allowed;
        }
        #${PANEL_ID} .valence-error { color: #be123c; font-size: 12px; margin-bottom: 10px; }
    `;

    const injectStyles = () => {
        if (document.getElementById("valence-mark-left-styles")) return;
        const tag = document.createElement("style");
        tag.id = "valence-mark-left-styles";
        tag.textContent = styles;
        document.head.appendChild(tag);
    };

    const closePanel = () => {
        const panel = document.getElementById(PANEL_ID);
        if (panel) panel.remove();
    };

    const openPanel = async () => {
        if (document.getElementById(PANEL_ID)) return;

        state.employee = "";
        state.employeeLabel = "";
        state.company = "";
        state.acknowledged = false;
        state.busy = false;

        const panel = document.createElement("div");
        panel.id = PANEL_ID;
        panel.innerHTML = `
            <div class="valence-card">
                <h3>Mark Employee as Left</h3>
                <div class="valence-error" hidden></div>
                <div class="valence-field">
                    <label>Employee</label>
                    <input type="text" class="valence-employee-search" placeholder="Search employee" autocomplete="off" />
                </div>
                <div class="valence-field">
                    <select class="valence-employee-select" size="5"></select>
                </div>
                <div class="valence-field">
                    <label>Left From</label>
                    <input type="date" class="valence-date" value="${state.date}" />
                </div>
                <div class="valence-warning">
                    <div class="valence-warning-text">Select an employee to continue.</div>
                    <label>
                        <input type="checkbox" class="valence-ack" />
                        I understand this cannot be undone from the Roster
                    </label>
                </div>
                <div class="valence-actions">
                    <button type="button" class="valence-cancel">Cancel</button>
                    <button type="button" class="valence-primary" disabled>Mark as Left</button>
                </div>
            </div>
        `;

        document.body.appendChild(panel);

        const search = panel.querySelector(".valence-employee-search");
        const select = panel.querySelector(".valence-employee-select");
        const dateInput = panel.querySelector(".valence-date");
        const ack = panel.querySelector(".valence-ack");
        const submit = panel.querySelector(".valence-primary");
        const warningText = panel.querySelector(".valence-warning-text");
        const errorBox = panel.querySelector(".valence-error");

        const showError = (message) => {
            errorBox.textContent = message || "";
            errorBox.hidden = !message;
        };

        const refreshState = () => {
            state.date = dateInput.value;
            state.acknowledged = ack.checked;
            warningText.innerHTML = state.employee
                ? `<b>${state.employeeLabel}</b> will be marked as <b>Left</b> from <b>${state.date || "the selected date"}</b>. This cannot be undone from the Roster.`
                : "Select an employee to continue.";
            submit.disabled = state.busy || !state.employee || !state.date || !state.acknowledged;
        };

        const loadEmployees = async (term) => {
            try {
                const rows = (await searchEmployees(term)) || [];
                select.innerHTML = rows
                    .map(
                        (row) =>
                            `<option value="${row.name}" data-company="${row.company || ""}">${row.employee_name || row.name} : ${row.name}</option>`
                    )
                    .join("");
                showError("");
            } catch (error) {
                showError(error.message);
            }
        };

        let searchTimer = null;
        search.addEventListener("input", () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => loadEmployees(search.value.trim()), 250);
        });

        select.addEventListener("change", () => {
            const option = select.selectedOptions[0];
            state.employee = option ? option.value : "";
            state.employeeLabel = option ? option.textContent.split(" : ")[0] : "";
            state.company = option ? option.dataset.company : "";
            refreshState();
        });

        dateInput.addEventListener("change", refreshState);
        ack.addEventListener("change", refreshState);
        panel.querySelector(".valence-cancel").addEventListener("click", closePanel);
        panel.addEventListener("click", (event) => {
            if (event.target === panel) closePanel();
        });

        submit.addEventListener("click", async () => {
            if (submit.disabled) return;
            state.busy = true;
            refreshState();
            submit.textContent = "Marking...";

            try {
                await call(INSERT_SHIFT_METHOD, {
                    employee: state.employee,
                    company: state.company,
                    shift_type: "",
                    start_date: state.date,
                    end_date: "",
                    status: "Left",
                });
                closePanel();
                window.location.reload();
            } catch (error) {
                state.busy = false;
                submit.textContent = "Mark as Left";
                showError(error.message);
                refreshState();
            }
        });

        await loadEmployees("");
        refreshState();
    };

    const findToolbarAnchor = () => {
        const buttons = Array.from(document.querySelectorAll("button"));
        return buttons.find((button) => button.textContent.trim().toLowerCase() === "create");
    };

    const mountButton = () => {
        if (document.getElementById(BUTTON_ID)) return true;

        const button = document.createElement("button");
        button.id = BUTTON_ID;
        button.type = "button";
        button.textContent = "Mark Employee Left";
        button.addEventListener("click", openPanel);

        const anchor = findToolbarAnchor();
        if (anchor && anchor.parentElement) {
            anchor.parentElement.insertBefore(button, anchor);
            return true;
        }

        button.classList.add("valence-floating");
        document.body.appendChild(button);
        return false;
    };

    const start = () => {
        injectStyles();

        let attempts = 0;
        const timer = setInterval(() => {
            attempts += 1;
            const placed = mountButton();
            if (placed || attempts > 40) clearInterval(timer);
        }, 250);
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
