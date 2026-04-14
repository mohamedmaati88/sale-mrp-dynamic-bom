from markupsafe import Markup
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleComponentSelectorLine(models.TransientModel):
    _name = 'sale.component.selector.line'
    _description = 'Sale Component Selector Line'
    _order = 'sequence, component_product_id'

    wizard_id = fields.Many2one(
        comodel_name='sale.component.selector',
        string='Wizard',
        required=True,
        ondelete='cascade',
    )
    selectable_component_id = fields.Many2one(
        comodel_name='mrp.selectable.component',
        string='Selectable Component',
        # Not required at ORM level — enforced explicitly in action_confirm
        # to avoid constraint errors from ghost rows in the ORM session.
    )
    component_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Component Product',
        related='selectable_component_id.component_product_id',
        readonly=True,
    )
    component_image = fields.Binary(
        string='Image',
        related='selectable_component_id.component_product_id.image_128',
        readonly=True,
        store=False,
    )
    component_image_full = fields.Binary(
        string='Full Image',
        related='selectable_component_id.component_product_id.image_1920',
        readonly=True,
        store=False,
    )
    group_id = fields.Many2one(
        comodel_name='mrp.component.group',
        string='Component Group',
        related='selectable_component_id.group_id',
        readonly=True,
        store=True,
    )
    group_selection_mode = fields.Selection(
        related='group_id.selection_mode',
        readonly=True,
    )
    qty = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit of Measure',
        related='selectable_component_id.uom_id',
        readonly=True,
    )
    packaging_qty = fields.Float(
        string='Units per Package',
        related='selectable_component_id.packaging_qty',
        readonly=True,
        digits='Product Unit of Measure',
    )
    margin = fields.Float(
        string='Margin',
        related='selectable_component_id.margin',
        readonly=True,
        digits='Product Price',
    )
    is_selected = fields.Boolean(string='Selected', default=False)
    is_mandatory = fields.Boolean(
        string='Mandatory',
        related='selectable_component_id.is_mandatory',
        readonly=True,
    )
    sequence = fields.Integer(
        string='Sequence',
        related='selectable_component_id.sequence',
        store=True,
    )
    notes = fields.Text(
        string='Notes',
        related='selectable_component_id.notes',
        readonly=True,
    )

    @api.onchange('qty')
    def _onchange_qty_check_max(self):
        sc = self.selectable_component_id
        if sc and sc.enable_max_qty and sc.max_qty > 0 and self.qty > sc.max_qty:
            return {
                'warning': {
                    'title': _('Maximum Quantity Exceeded'),
                    'message': _('Quantity %.2f exceeds the maximum allowed quantity of %.2f for "%s".')
                               % (self.qty, sc.max_qty, sc.component_product_id.display_name),
                }
            }

    @api.onchange('is_selected')
    def _onchange_is_selected(self):
        """Auto-deselect others in the same single-selection group."""
        if self.is_selected and self.group_id and self.group_id.selection_mode == 'single':
            for line in self.wizard_id.line_ids:
                if (
                    line != self
                    and line.group_id == self.group_id
                    and line.is_selected
                    and not line.is_mandatory
                ):
                    line.is_selected = False


class SaleComponentSelector(models.TransientModel):
    _name = 'sale.component.selector'
    _description = 'Sale Component Selector Wizard'

    sale_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Sale Order Line',
        required=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        related='sale_line_id.product_id',
        readonly=True,
    )
    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string='Product Template',
        related='sale_line_id.product_id.product_tmpl_id',
        readonly=True,
    )
    line_ids = fields.One2many(
        comodel_name='sale.component.selector.line',
        inverse_name='wizard_id',
        string='Component Lines',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        Create wizard record(s) AND immediately create their lines as real
        DB records.  This guarantees that when the form opens with a res_id,
        line_ids are real persisted records — not virtual default_get ghosts
        that can silently disappear before action_confirm runs.
        """
        records = super().create(vals_list)
        Line = self.env['sale.component.selector.line']
        for record in records:
            if record.sale_line_id and not record.line_ids:
                line_vals = record._build_line_vals()
                if line_vals:
                    Line.create(line_vals)
        return records

    def _build_line_vals(self):
        """
        Return a list of dicts for sale.component.selector.line creation.
        Reads directly from mrp.selectable.component (not related fields)
        so values are always fresh and correct.
        """
        self.ensure_one()
        sale_line = self.sale_line_id
        already_selected_ids = sale_line.selected_component_ids.mapped(
            'selectable_component_id'
        ).ids

        vals_list = []
        for comp in sale_line.product_id.product_tmpl_id.selectable_component_ids:
            is_selected = comp.is_mandatory or comp.id in already_selected_ids
            qty = comp.qty_default
            # Preserve quantity the user previously entered
            existing = sale_line.selected_component_ids.filtered(
                lambda c, cid=comp.id: c.selectable_component_id.id == cid
            )
            if existing:
                qty = existing[0].qty
            vals_list.append({
                'wizard_id': self.id,
                'selectable_component_id': comp.id,
                'is_selected': is_selected,
                'qty': qty,
            })
        return vals_list

    def action_confirm(self):
        self.ensure_one()
        sale_line = self.sale_line_id

        # Only work with lines that have a real selectable_component_id
        valid_lines = self.line_ids.filtered(lambda l: l.selectable_component_id)

        # ── Validate mandatory components ──────────────────────────────────
        for line in valid_lines:
            if line.is_mandatory and not line.is_selected:
                raise UserError(
                    _('Component "%s" is mandatory and cannot be deselected.')
                    % line.selectable_component_id.component_product_id.display_name
                )

        # ── Validate max quantity limits ───────────────────────────────────
        max_qty_errors = []
        for line in valid_lines.filtered(lambda l: l.is_selected):
            sc = line.selectable_component_id
            if sc.enable_max_qty and sc.max_qty > 0 and line.qty > sc.max_qty:
                max_qty_errors.append(
                    '• %s: entered %.2f, maximum allowed is %.2f'
                    % (sc.component_product_id.display_name, line.qty, sc.max_qty)
                )
        if max_qty_errors:
            raise UserError(
                _('The following components exceed their maximum allowed quantity:\n\n%s')
                % '\n'.join(max_qty_errors)
            )

        # ── Validate group rules ───────────────────────────────────────────
        seen_groups = valid_lines.mapped('selectable_component_id').mapped('group_id')
        for group in seen_groups:
            group_lines = valid_lines.filtered(
                lambda l: l.selectable_component_id.group_id == group
            )
            selected = group_lines.filtered(lambda l: l.is_selected)

            if group.is_required and not selected:
                raise UserError(
                    _('At least one component must be selected from required '
                      'group "%s".') % group.name
                )
            if group.selection_mode == 'single' and len(selected) > 1:
                raise UserError(
                    _('Only one component can be selected from single-selection '
                      'group "%s". Please deselect the extras.') % group.name
                )

        # ── Validate component incompatibilities ──────────────────────────────
        selected_sc = valid_lines.filtered(lambda l: l.is_selected).mapped(
            'selectable_component_id'
        )
        incompat_errors = []
        checked_pairs = set()
        for sc in selected_sc:
            for incompat in sc.incompatible_component_ids:
                if incompat in selected_sc:
                    pair = frozenset([sc.id, incompat.id])
                    if pair not in checked_pairs:
                        checked_pairs.add(pair)
                        incompat_errors.append(
                            '• "%s"  ↔  "%s"'
                            % (
                                sc.component_product_id.display_name,
                                incompat.component_product_id.display_name,
                            )
                        )
        if incompat_errors:
            raise UserError(
                _('The following selected components are incompatible and '
                  'cannot be used together:\n\n%s\n\n'
                  'Please deselect one component from each conflicting pair.')
                % '\n'.join(incompat_errors)
            )

        # ── Duplicate detection ────────────────────────────────────────────
        # Build a fingerprint: frozenset of (selectable_component_id, qty).
        incoming = frozenset(
            (line.selectable_component_id.id, line.qty)
            for line in valid_lines.filtered(lambda l: l.is_selected)
        )
        incoming_product = sale_line.product_id

        other_lines = sale_line.order_id.order_line.filtered(
            lambda l: l.id != sale_line.id
            and l.product_id == incoming_product
            and l.has_dynamic_components
        )

        exact_match_line = None
        diff_spec_lines = []
        for other in other_lines:
            other_fp = frozenset(
                (c.selectable_component_id.id, c.qty)
                for c in other.selected_component_ids
            )
            if other_fp == incoming:
                exact_match_line = other
                break
            diff_spec_lines.append(other)

        if exact_match_line:
            raise UserError(
                _('Product "%s" already exists in this sale order with the exact same '
                  'components and quantities (line %s). Duplicate entries are not allowed.')
                % (incoming_product.display_name, exact_match_line.sequence or '')
            )

        # For different specs: collect warning message but proceed with saving.
        diff_warning_msg = None
        if diff_spec_lines:
            line_nums = ', '.join(str(l.sequence or '') for l in diff_spec_lines)
            diff_warning_msg = (
                'Product "%s" already exists in this sale order with different '
                'component specifications (line(s): %s).'
                % (incoming_product.display_name, line_nums)
            )

        # ── Persist selections on the SO line ─────────────────────────────
        sale_line.selected_component_ids.unlink()

        components_vals = []
        for line in valid_lines.filtered(lambda l: l.is_selected):
            sc = line.selectable_component_id   # read from source, not related field
            components_vals.append({
                'sale_line_id': sale_line.id,
                'selectable_component_id': sc.id,
                'component_product_id': sc.component_product_id.id,
                'group_id': sc.group_id.id if sc.group_id else False,
                'qty': line.qty,
                'uom_id': sc.uom_id.id,
                'packaging_qty': sc.packaging_qty,
                'margin': sc.margin,
                'sequence': sc.sequence,
                'notes': sc.notes or False,
            })

        if not components_vals:
            raise UserError(_('No components were selected. Please select at least one component.'))

        self.env['sale.order.line.component'].create(components_vals)

        # components_configured is computed — recomputes automatically

        # ── Chatter ───────────────────────────────────────────────────────
        sale_line.order_id.message_post(
            body=Markup('Components configured for product <b>%s</b> (line %s): '
                        '%d component(s) selected.') % (
                sale_line.product_id.display_name,
                sale_line.sequence or '',
                len(components_vals),
            )
        )

        # ── Create MO immediately if SO is already confirmed ──────────────
        # For confirmed SOs, we create the MO right here instead of waiting
        # for the user to save the SO — simpler and more predictable UX.
        order = sale_line.order_id
        if order.state == 'sale':
            existing_mo = self.env['mrp.production'].sudo().search([
                ('is_dynamic_bom', '=', True),
                ('dynamic_sale_line_id', '=', sale_line.id),
                ('state', 'not in', ['done', 'cancel']),
            ], limit=1)
            if not existing_mo:
                sale_line._action_launch_stock_rule()
            order._setup_dynamic_bom_on_productions()

        if diff_warning_msg:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Duplicate Product Warning',
                    'message': diff_warning_msg,
                    'type': 'warning',
                    'sticky': True,
                    'next': {'type': 'ir.actions.act_window_close'},
                },
            }
        return {'type': 'ir.actions.act_window_close'}
