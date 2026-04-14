/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

// ── Save-block bypass for Configure button ────────────────────────────────
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

// ── Component image lightbox with mouse-wheel zoom ────────────────────────
(function () {
    let scale     = 1;
    let tx        = 0;   // translate X
    let ty        = 0;   // translate Y
    let dragging  = false;
    let dragMoved = false;
    let startX    = 0;
    let startY    = 0;

    /* ── Build overlay (lazy — on first click) ── */
    let overlay, img, hint;

    function build() {
        if (overlay) return;

        overlay = document.createElement("div");
        overlay.style.cssText =
            "display:none;position:fixed;inset:0;" +
            "background:rgba(0,0,0,0.92);z-index:99999;" +
            "overflow:hidden;cursor:zoom-out;";

        img = document.createElement("img");
        img.style.cssText =
            "position:absolute;top:50%;left:50%;" +
            "transform-origin:center center;" +
            "border-radius:8px;" +
            "box-shadow:0 8px 40px rgba(0,0,0,0.6);" +
            "user-select:none;pointer-events:none;";

        hint = document.createElement("div");
        hint.style.cssText =
            "position:absolute;bottom:16px;left:50%;" +
            "transform:translateX(-50%);" +
            "color:rgba(255,255,255,0.45);font-size:12px;" +
            "white-space:nowrap;pointer-events:none;";
        hint.textContent = "Scroll to zoom  •  Drag to pan  •  Click or Esc to close";

        overlay.appendChild(img);
        overlay.appendChild(hint);
        document.body.appendChild(overlay);

        /* wheel → zoom */
        overlay.addEventListener("wheel", (ev) => {
            ev.preventDefault();
            const step  = ev.deltaY < 0 ? 0.15 : -0.15;
            scale = Math.min(Math.max(scale + step, 0.5), 8);
            applyTransform();
            overlay.style.cursor = scale > 1 ? "grab" : "zoom-out";
        }, { passive: false });

        /* mousedown → start drag */
        overlay.addEventListener("mousedown", (ev) => {
            if (ev.button !== 0) return;
            dragging  = true;
            dragMoved = false;
            startX    = ev.clientX - tx;
            startY    = ev.clientY - ty;
            overlay.style.cursor = "grabbing";
        });

        document.addEventListener("mousemove", (ev) => {
            if (!dragging) return;
            tx = ev.clientX - startX;
            ty = ev.clientY - startY;
            dragMoved = true;
            applyTransform();
        });

        document.addEventListener("mouseup", () => {
            if (!dragging) return;
            dragging = false;
            overlay.style.cursor = scale > 1 ? "grab" : "zoom-out";
        });

        /* click → close (only when not dragging) */
        overlay.addEventListener("click", () => {
            if (dragMoved) { dragMoved = false; return; }
            close();
        });

        /* double-click → reset zoom */
        overlay.addEventListener("dblclick", () => {
            scale = 1; tx = 0; ty = 0;
            applyTransform();
            overlay.style.cursor = "zoom-out";
        });

        document.addEventListener("keydown", (ev) => {
            if (ev.key === "Escape") close();
        });
    }

    function applyTransform() {
        img.style.transform =
            "translate(calc(-50% + " + tx + "px), calc(-50% + " + ty + "px)) scale(" + scale + ")";
    }

    function close() {
        if (!overlay) return;
        overlay.style.display = "none";
        img.src = "";
        scale = 1; tx = 0; ty = 0;
        applyTransform();
    }

    /* ── Click on thumbnail → open lightbox with full image ── */
    document.addEventListener("click", (ev) => {
        const thumb = ev.target.closest(".o_component_image img");
        if (!thumb) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();

        build();

        /* Prefer the hidden full-resolution image in the same row */
        const row     = thumb.closest("tr");
        const fullImg = row && row.querySelector(".o_component_image_full img");
        img.src = (fullImg && fullImg.src) ? fullImg.src : thumb.src;

        scale = 1; tx = 0; ty = 0;
        applyTransform();
        overlay.style.display = "block";
        overlay.style.cursor  = "zoom-out";
    }, true);
})();
