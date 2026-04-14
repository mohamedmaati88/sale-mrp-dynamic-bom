from odoo import _, api, fields, models
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
    component_image = fields.Binary(
        string='Image',
        related='component_product_id.image_128',
        readonly=True,
        store=False,
    )
    component_image_full = fields.Binary(
        string='Full Image',
        related='component_product_id.image_1920',
        readonly=True,
        store=False,
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
    allowed_uom_ids = fields.Many2many(
        comodel_name='uom.uom',
        compute='_compute_allowed_uom_ids',
        string='Allowed UoMs',
    )
    packaging_qty = fields.Float(
        string='Units per Package',
        default=1.0,
        digits='Product Unit of Measure',
        help='Number of base units in one package (e.g. 20 for a Carton of 20). '
             'Use 1 for no packaging multiplier. '
             'Subtotal = unit_price × qty × packaging_qty.',
    )
    margin = fields.Float(
        string='Margin',
        default=0.0,
        digits='Product Price',
        help='Margin applied to component cost when pricing_mode = Components Cost.\n'
             'Percentage: unit_price = cost × (1 + margin/100).\n'
             'Fixed Amount: unit_price = cost + margin.',
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

    @api.depends('component_product_id')
    def _compute_allowed_uom_ids(self):
        for rec in self:
            if not rec.component_product_id:
                rec.allowed_uom_ids = False
                continue
            product = rec.component_product_id
            # Base UoM + any extra UoMs defined on the product's Sales tab
            uoms = product.uom_id
            if 'uom_ids' in product._fields and product.uom_ids:
                uoms |= product.uom_ids
            rec.allowed_uom_ids = uoms

    @api.onchange('component_product_id')
    def _onchange_component_product_id(self):
        """Auto-fill UoM from the selected component product and reset packaging_qty."""
        if self.component_product_id:
            self.uom_id = self.component_product_id.uom_id
            # Auto-fill margin from product template default_margin
            self.margin = self.product_tmpl_id.default_margin or 0.0
            self.packaging_qty = 1.0

    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        """Auto-update packaging_qty from the UoM conversion factor vs base UoM."""
        if not self.uom_id or not self.component_product_id:
            return
        base_uom = self.component_product_id.uom_id
        if not base_uom or self.uom_id == base_uom:
            self.packaging_qty = 1.0
            return
        try:
            # How many base units = 1 unit of the selected UoM
            self.packaging_qty = self.uom_id._compute_quantity(1.0, base_uom)
        except Exception:
            self.packaging_qty = 1.0

    @api.model_create_multi
    def create(self, vals_list):
        """Ensure uom_id is always set from the component product on create."""
        for vals in vals_list:
            if vals.get('component_product_id') and not vals.get('uom_id'):
                product = self.env['product.product'].browse(vals['component_product_id'])
                vals['uom_id'] = product.uom_id.id
        return super().create(vals_list)

    def write(self, vals):
        """Auto-applies the reciprocal incompatibility relationship so that
        if A marks B as incompatible, B is automatically also marked as
        incompatible with A — without infinite recursion.
        """

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
                        _('A component cannot be incompatible with itself ("%s").')
                        % rec.component_product_id.display_name
                    )
                if incompat.product_tmpl_id != rec.product_tmpl_id:
                    raise ValidationError(
                        _('Incompatible component "%s" belongs to a different product. '
                          'Incompatibilities must be within the same product\'s '
                          'component list.')
                        % incompat.component_product_id.display_name
                    )

    _sql_constraints = [
        (
            'unique_component_per_product',
            'UNIQUE(product_tmpl_id, component_product_id)',
            'Component must be unique per product',
        ),
    ]
