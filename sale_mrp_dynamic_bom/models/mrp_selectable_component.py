from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MrpSelectableComponent(models.Model):
    _name = 'mrp.selectable.component'
    _description = 'MRP Selectable Component'
    _order = 'sequence, group_id, component_product_id'
    _rec_name = 'component_product_id'

    product_tmpl_id = fields.Many2one(
        comodel_name='product.template',
        string='Product Template',
        required=True,
        ondelete='cascade',
        index=True,
    )
    component_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Component Product',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])],
    )
    group_id = fields.Many2one(
        comodel_name='mrp.component.group',
        string='Component Group',
        required=True,
    )
    qty_default = fields.Float(
        string='Default Quantity',
        default=1.0,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unit of Measure',
        required=True,
    )
    is_mandatory = fields.Boolean(
        string='Mandatory',
        help='Always included, user cannot deselect',
    )
    enable_max_qty = fields.Boolean(
        string='Max Qty',
        default=False,
        help='Enable a maximum quantity limit for this component on sale order lines.',
    )
    max_qty = fields.Float(
        string='Max Quantity',
        digits='Product Unit of Measure',
        help='Maximum quantity the user can enter for this component on a sale order.',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    notes = fields.Text(string='Notes')

    # ── Incompatibility (self-referential M2M) ────────────────────────────────
    incompatible_component_ids = fields.Many2many(
        comodel_name='mrp.selectable.component',
        relation='mrp_selectable_component_incompat_rel',
        column1='component_id',
        column2='incompatible_id',
        string='Incompatible With',
        help='Components that cannot be selected together with this one '
             'on the same sale order line.',
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        related='product_tmpl_id.company_id',
        store=True,
    )

    @api.onchange('component_product_id')
    def _onchange_component_product_id(self):
        """Auto-fill UoM from the selected component product."""
        if self.component_product_id:
            self.uom_id = self.component_product_id.uom_id

    @api.model_create_multi
    def create(self, vals_list):
        """Ensure uom_id is always set from the component product on create."""
        for vals in vals_list:
            if vals.get('component_product_id') and not vals.get('uom_id'):
                product = self.env['product.product'].browse(vals['component_product_id'])
                vals['uom_id'] = product.uom_id.id
        return super().create(vals_list)

    def write(self, vals):
        """Ensure uom_id stays in sync when component_product_id changes.
        Also auto-applies the reciprocal incompatibility relationship so that
        if A marks B as incompatible, B is automatically also marked as
        incompatible with A — without infinite recursion.
        """
        if vals.get('component_product_id') and not vals.get('uom_id'):
            product = self.env['product.product'].browse(vals['component_product_id'])
            vals['uom_id'] = product.uom_id.id

        # Capture pre-write incompatible sets for reciprocal sync
        if 'incompatible_component_ids' in vals and not self.env.context.get('_incompat_reciprocal'):
            before = {rec.id: set(rec.incompatible_component_ids.ids) for rec in self}
            result = super().write(vals)
            ctx = dict(self.env.context, _incompat_reciprocal=True)
            for rec in self:
                after = set(rec.incompatible_component_ids.ids)
                added = after - before.get(rec.id, set())
                removed = before.get(rec.id, set()) - after
                for added_id in added:
                    incompat = self.browse(added_id)
                    if rec.id not in incompat.incompatible_component_ids.ids:
                        incompat.with_context(**ctx).write(
                            {'incompatible_component_ids': [(4, rec.id)]}
                        )
                for removed_id in removed:
                    incompat = self.browse(removed_id)
                    if rec.id in incompat.incompatible_component_ids.ids:
                        incompat.with_context(**ctx).write(
                            {'incompatible_component_ids': [(3, rec.id)]}
                        )
            return result

        return super().write(vals)

    @api.constrains('incompatible_component_ids', 'product_tmpl_id')
    def _check_incompatible_components(self):
        for rec in self:
            for incompat in rec.incompatible_component_ids:
                if incompat.id == rec.id:
                    raise ValidationError(
                        'A component cannot be incompatible with itself ("%s").'
                        % rec.component_product_id.display_name
                    )
                if incompat.product_tmpl_id != rec.product_tmpl_id:
                    raise ValidationError(
                        'Incompatible component "%s" belongs to a different product. '
                        'Incompatibilities must be within the same product\'s '
                        'component list.'
                        % incompat.component_product_id.display_name
                    )

    _sql_constraints = [
        (
            'unique_component_per_product',
            'UNIQUE(product_tmpl_id, component_product_id)',
            'Component must be unique per product',
        ),
    ]
