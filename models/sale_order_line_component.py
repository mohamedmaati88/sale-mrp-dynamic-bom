from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class SaleOrderLineComponent(models.Model):
    _name = 'sale.order.line.component'
    _description = 'Sale Order Line Component'
    _order = 'sequence, group_id, component_product_id'

    sale_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Sale Order Line',
        required=True,
        ondelete='cascade',
        index=True,
        default=lambda self: self.env.context.get('default_sale_line_id'),
    )
    selectable_component_id = fields.Many2one(
        comodel_name='mrp.selectable.component',
        string='Selectable Component',
        ondelete='restrict',
    )
    component_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Component Product',
        required=True,
    )
    group_id = fields.Many2one(
        comodel_name='mrp.component.group',
        string='Component Group',
    )
    qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False),
    )
    sale_price = fields.Float(
        string='Unit Price',
        related='component_product_id.lst_price',
        digits='Product Price',
        readonly=True,
    )
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        digits='Product Price',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    notes = fields.Text(string='Notes')

    @api.depends('component_product_id', 'qty')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.component_product_id.lst_price * rec.qty

    # ── Computed: allowed products for this SO line ───────────────────────
    allowed_product_ids = fields.Many2many(
        comodel_name='product.product',
        string='Allowed Products',
        compute='_compute_allowed_product_ids',
    )

    @api.depends('sale_line_id', 'sale_line_id.product_id')
    def _compute_allowed_product_ids(self):
        for rec in self:
            selectable = rec.sale_line_id.product_id.product_tmpl_id.selectable_component_ids
            rec.allowed_product_ids = selectable.mapped('component_product_id')

    # ── Onchange: validate max qty in real time ───────────────────────────
    @api.onchange('qty')
    def _onchange_qty_check_max(self):
        sc = self.selectable_component_id
        if sc and sc.enable_max_qty and sc.max_qty > 0 and self.qty > sc.max_qty:
            return {
                'warning': {
                    'title': 'Maximum Quantity Exceeded',
                    'message': 'Quantity %.2f exceeds the maximum allowed quantity of %.2f for "%s".'
                               % (self.qty, sc.max_qty, sc.component_product_id.display_name),
                }
            }

    # ── Onchange: auto-fill group, uom, qty from selectable definition ────
    @api.onchange('component_product_id')
    def _onchange_component_product_id(self):
        if not self.component_product_id or not self.sale_line_id:
            return
        selectable = self.sale_line_id.product_id.product_tmpl_id.selectable_component_ids.filtered(
            lambda s: s.component_product_id == self.component_product_id
        )
        if selectable:
            sc = selectable[0]
            self.group_id = sc.group_id
            self.uom_id = sc.uom_id
            self.qty = sc.qty_default if sc.qty_default else 1.0
            self.selectable_component_id = sc

    # ── Constraint: only allow products in the selectable list ────────────
    # ── Flag parent SO line and SO as needing sync on any change ─────────
    def _flag_so_needs_sync(self):
        lines = self.mapped('sale_line_id')
        if lines:
            lines.sudo().write({
                'line_components_need_sync': True,
                'line_price_needs_sync': True,
            })
        orders = lines.mapped('order_id')
        if orders:
            orders.sudo().with_context(skip_mo_setup=True).write({
                'components_need_sync': True,
                'price_needs_sync': True,
            })

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._flag_so_needs_sync()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._flag_so_needs_sync()
        return res

    def unlink(self):
        self._flag_so_needs_sync()
        return super().unlink()

    @api.constrains('selectable_component_id', 'sale_line_id')
    def _check_incompatible_with_siblings(self):
        """Safety-net: block saving a component that is incompatible with an
        already-saved sibling on the same SO line.

        Note: this constraint fires per-record so it catches individual adds
        (e.g. direct ORM writes). The wizard validates the full selection
        BEFORE writing, so the user-facing error always comes from there.
        """
        for rec in self:
            if not rec.selectable_component_id or not rec.sale_line_id:
                continue
            siblings = rec.sale_line_id.selected_component_ids.filtered(
                lambda c: c.id != rec.id and c.selectable_component_id
            )
            for sib in siblings:
                if sib.selectable_component_id in \
                        rec.selectable_component_id.incompatible_component_ids:
                    raise ValidationError(
                        'Component "%s" is incompatible with "%s". '
                        'These components cannot be selected together on the same sale order line.'
                        % (
                            rec.selectable_component_id.component_product_id.display_name,
                            sib.selectable_component_id.component_product_id.display_name,
                        )
                    )

    @api.constrains('qty', 'selectable_component_id')
    def _check_max_qty(self):
        for rec in self:
            sc = rec.selectable_component_id
            if sc and sc.enable_max_qty and sc.max_qty > 0 and rec.qty > sc.max_qty:
                raise ValidationError(
                    'Quantity %.2f for component "%s" exceeds the maximum allowed quantity of %.2f.'
                    % (rec.qty, sc.component_product_id.display_name, sc.max_qty)
                )

    @api.constrains('component_product_id', 'sale_line_id')
    def _check_allowed_component(self):
        for rec in self:
            allowed = rec.sale_line_id.product_id.product_tmpl_id.selectable_component_ids.mapped(
                'component_product_id'
            )
            if allowed and rec.component_product_id not in allowed:
                raise ValidationError(
                    'Product "%s" is not in the allowed selectable components '
                    'for "%s".' % (
                        rec.component_product_id.display_name,
                        rec.sale_line_id.product_id.display_name,
                    )
                )
