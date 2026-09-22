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
            fields: ["name", "employee_name", "company", "designation"],
            limit_page_length: 50,
            order_by: "employee_name asc",
        });

    const escapeHtml = (value) =>
        String(value == null ? "" : value).replace(/[&<>"']/g, (char) => {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
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
        #${PANEL_ID} * { box-sizing: border-box; }
        #${PANEL_ID} .valence-card {
            width: 440px;
            max-width: calc(100vw - 32px);
            background: #fff;
            border-radius: 12px;
            padding: 20px;
            font-family: inherit;
            color: #1f2937;
            box-shadow: 0 20px 50px rgba(15, 23, 42, 0.2);
        }
        #${PANEL_ID} h3 { margin: 0 0 16px; font-size: 16px; font-weight: 600; }
        #${PANEL_ID} .valence-label {
            display: block;
            font-size: 12px;
            color: #6b7280;
            margin-bottom: 6px;
        }
        #${PANEL_ID} input[type="text"],
        #${PANEL_ID} input[type="date"] {
            width: 100%;
            height: 32px;
            padding: 0 10px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 13px;
            background: #fff;
            color: #1f2937;
            outline: none;
        }
        #${PANEL_ID} input[type="text"]:focus,
        #${PANEL_ID} input[type="date"]:focus {
            border-color: #9ca3af;
            box-shadow: 0 0 0 2px rgba(148, 163, 184, 0.25);
        }
        #${PANEL_ID} .valence-field { margin-bottom: 16px; }
        #${PANEL_ID} .valence-emp-list {
            margin-top: 8px;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            max-height: 190px;
            overflow-y: auto;
            background: #fff;
        }
        #${PANEL_ID} .valence-emp-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            padding: 8px 10px;
            font-size: 13px;
            cursor: pointer;
            border-bottom: 1px solid #f3f4f6;
        }
        #${PANEL_ID} .valence-emp-item:last-child { border-bottom: 0; }
        #${PANEL_ID} .valence-emp-item:hover { background: #f9fafb; }
        #${PANEL_ID} .valence-emp-item.is-selected {
            background: #fff1f2;
            color: #be123c;
            font-weight: 500;
        }
        #${PANEL_ID} .valence-emp-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
        #${PANEL_ID} .valence-emp-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        #${PANEL_ID} .valence-emp-sub { font-size: 11px; color: #9ca3af; font-weight: 400; }
        #${PANEL_ID} .valence-emp-id { font-size: 11px; color: #9ca3af; white-space: nowrap; }
        #${PANEL_ID} .valence-emp-empty {
            padding: 14px 10px;
            font-size: 13px;
            color: #9ca3af;
            text-align: center;
        }
        #${PANEL_ID} .valence-warning {
            border: 1px solid #fecdd3;
            background: #fff1f2;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 16px;
        }
        #${PANEL_ID} .valence-warning-text {
            font-size: 13px;
            color: #be123c;
            line-height: 1.5;
        }
        #${PANEL_ID} .valence-ack-row {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid #fecdd3;
            cursor: pointer;
            user-select: none;
        }
        #${PANEL_ID} .valence-ack-row input[type="checkbox"] {
            width: 16px;
            height: 16px;
            min-width: 16px;
            margin: 0;
            accent-color: #e11d48;
            cursor: pointer;
        }
        #${PANEL_ID} .valence-ack-row span { font-size: 13px; color: #9f1239; }
        #${PANEL_ID} .valence-actions { display: flex; justify-content: flex-end; gap: 8px; }
        #${PANEL_ID} button {
            height: 32px;
            padding: 0 14px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            border: 1px solid #d1d5db;
            background: #fff;
            color: #1f2937;
        }
        #${PANEL_ID} button:hover { background: #f9fafb; }
        #${PANEL_ID} button.valence-primary {
            background: #e11d48;
            border-color: #e11d48;
            color: #fff;
        }
        #${PANEL_ID} button.valence-primary:hover { background: #be123c; }
        #${PANEL_ID} button.valence-primary:disabled {
            background: #fda4af;
            border-color: #fda4af;
            cursor: not-allowed;
        }
        #${PANEL_ID} .valence-error {
            color: #be123c;
            font-size: 12px;
            margin-bottom: 12px;
            padding: 8px 10px;
            border-radius: 8px;
            background: #fff1f2;
        }
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
                    <span class="valence-label">Employee</span>
                    <input type="text" class="valence-employee-search" placeholder="Search by name or ID" autocomplete="off" />
                    <div class="valence-emp-list">
                        <div class="valence-emp-empty">Loading employees...</div>
                    </div>
                </div>
                <div class="valence-field">
                    <span class="valence-label">Left From</span>
                    <input type="date" class="valence-date" value="${state.date}" />
                </div>
                <div class="valence-warning">
                    <div class="valence-warning-text">Select an employee to continue.</div>
                    <label class="valence-ack-row">
                        <input type="checkbox" class="valence-ack" />
                        <span>I understand this cannot be undone from the Roster</span>
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
        const list = panel.querySelector(".valence-emp-list");
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
                ? `<b>${escapeHtml(state.employeeLabel)}</b> will be marked as <b>Left</b> from <b>${escapeHtml(state.date || "")}</b>. This cannot be undone from the Roster.`
                : "Select an employee to continue.";
            submit.disabled = state.busy || !state.employee || !state.date || !state.acknowledged;
        };

        const selectRow = (row) => {
            list.querySelectorAll(".valence-emp-item").forEach((item) => {
                item.classList.toggle("is-selected", item === row);
            });
            state.employee = row.dataset.employee;
            state.employeeLabel = row.dataset.label;
            state.company = row.dataset.company;
            refreshState();
        };

        const renderRows = (rows) => {
            if (!rows.length) {
                list.innerHTML = '<div class="valence-emp-empty">No matching employee</div>';
                return;
            }

            list.innerHTML = rows
                .map((row) => {
                    const label = row.employee_name || row.name;
                    return `
                        <div class="valence-emp-item" data-employee="${escapeHtml(row.name)}" data-label="${escapeHtml(label)}" data-company="${escapeHtml(row.company || "")}">
                            <span class="valence-emp-main">
                                <span class="valence-emp-name">${escapeHtml(label)}</span>
                                ${row.designation ? `<span class="valence-emp-sub">${escapeHtml(row.designation)}</span>` : ""}
                            </span>
                            <span class="valence-emp-id">${escapeHtml(row.name)}</span>
                        </div>
                    `;
                })
                .join("");

            list.querySelectorAll(".valence-emp-item").forEach((item) => {
                item.addEventListener("click", () => selectRow(item));
            });
        };

        const loadEmployees = async (term) => {
            list.innerHTML = '<div class="valence-emp-empty">Loading employees...</div>';
            try {
                renderRows((await searchEmployees(term)) || []);
                showError("");
            } catch (error) {
                list.innerHTML = '<div class="valence-emp-empty">Could not load employees</div>';
                showError(error.message);
            }
        };

        let searchTimer = null;
        search.addEventListener("input", () => {
            state.employee = "";
            state.employeeLabel = "";
            refreshState();
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => loadEmployees(search.value.trim()), 250);
        });

        dateInput.addEventListener("change", refreshState);
        ack.addEventListener("change", refreshState);
        panel.querySelector(".valence-cancel").addEventListener("click", closePanel);
        panel.addEventListener("click", (event) => {
            if (event.target === panel) closePanel();
        });
        document.addEventListener("keydown", function onEscape(event) {
            if (event.key !== "Escape") return;
            document.removeEventListener("keydown", onEscape);
            closePanel();
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
        return buttons.find((button) => {
            if (button.id === BUTTON_ID) return false;
            return button.textContent.trim().toLowerCase() === "create";
        });
    };

    const getButton = () => {
        let button = document.getElementById(BUTTON_ID);
        if (button) return button;

        button = document.createElement("button");
        button.id = BUTTON_ID;
        button.type = "button";
        button.textContent = "Mark Employee Left";
        button.addEventListener("click", openPanel);
        return button;
    };

    const mountButton = () => {
        const button = getButton();
        const anchor = findToolbarAnchor();

        if (anchor && anchor.parentElement) {
            if (button.nextElementSibling !== anchor || button.parentElement !== anchor.parentElement) {
                button.classList.remove("valence-floating");
                anchor.parentElement.insertBefore(button, anchor);
            }
            return true;
        }

        if (!button.isConnected) {
            button.classList.add("valence-floating");
            document.body.appendChild(button);
        }
        return false;
    };

    const start = () => {
        injectStyles();

        let attempts = 0;
        const timer = setInterval(() => {
            attempts += 1;
            const placed = mountButton();
            if (placed || attempts > 120) clearInterval(timer);
        }, 250);

        const observer = new MutationObserver(() => mountButton());
        observer.observe(document.body, { childList: true, subtree: true });
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", start);
    } else {
        start();
    }
})();
