/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// ── Save-block bypass for Configure button ────────────────────────────────
// Capture-phase listener sets this flag when Configure is clicked so the
// auto-save that immediately follows skips the unconfigured-line check.
let _bypassForConfigure = false;

document.addEventListener(
    "click",
    (ev) => {
        if (ev.target.closest(".o_dynamic_bom_configure")) {
            _bypassForConfigure = true;
        }
    },
    true
);

patch(FormController.prototype, {
    async save(options = {}) {
        if (_bypassForConfigure) {
            _bypassForConfigure = false;
        }
        return super.save(options);
    },
});
